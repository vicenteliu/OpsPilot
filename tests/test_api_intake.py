"""POST /api/intake — webhook intake: accept-async, dedupe, retry-on-raise.

Uses ``TestClient`` with the run handler patched out, so no provider or
storage is touched; TestClient executes background tasks before returning.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.intake import router as intake_router
from opspilot.api.types import ApiRunResponse

_OK_RUN = ApiRunResponse(
    session_id="ses_wh",
    artifact_id="art_1",
    schema_valid=True,
    result={"summary": "ok"},
    error=None,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(intake_router, prefix="/api")
    return app


def _payload(key: str = "MON-1042") -> dict[str, Any]:
    return {
        "key": key,
        "input": {"ticket_id": key, "subject": "disk full", "body": "on host db-3"},
    }


class TestWebhookIntake:
    def test_accepts_and_runs_in_background(self) -> None:
        with (
            patch(
                "opspilot.api.routes.intake.run_ticket", new=AsyncMock(return_value=_OK_RUN)
            ) as run,
            TestClient(_app()) as client,
        ):
            res = client.post("/api/intake", json=_payload())
        assert res.status_code == 202
        assert res.json() == {"accepted": True, "duplicate": False, "key": "MON-1042"}
        assert run.await_count == 1
        assert run.await_args.args[0].input["ticket_id"] == "MON-1042"

    def test_duplicate_key_not_rerun(self) -> None:
        with (
            patch(
                "opspilot.api.routes.intake.run_ticket", new=AsyncMock(return_value=_OK_RUN)
            ) as run,
            TestClient(_app()) as client,
        ):
            first = client.post("/api/intake", json=_payload())
            second = client.post("/api/intake", json=_payload())
        assert first.status_code == 202
        assert second.status_code == 200
        assert second.json()["duplicate"] is True
        assert run.await_count == 1

    def test_playbook_and_model_passed_through(self) -> None:
        payload = {
            **_payload(),
            "playbook_id": "pb_x",
            "model_id": "anthropic/claude-haiku-4-5-20251001",
        }
        with (
            patch(
                "opspilot.api.routes.intake.run_ticket", new=AsyncMock(return_value=_OK_RUN)
            ) as run,
            TestClient(_app()) as client,
        ):
            client.post("/api/intake", json=payload)
        body = run.await_args.args[0]
        assert body.playbook_id == "pb_x"
        assert body.model_id == "anthropic/claude-haiku-4-5-20251001"

    def test_raised_run_forgets_key_so_redelivery_retries(self) -> None:
        boom = AsyncMock(side_effect=RuntimeError("provider down"))
        with (
            patch("opspilot.api.routes.intake.run_ticket", new=boom) as run,
            TestClient(_app()) as client,
        ):
            first = client.post("/api/intake", json=_payload())
            second = client.post("/api/intake", json=_payload())
        assert first.status_code == 202
        # The raise forgot the key → the redelivery is accepted and retried.
        assert second.status_code == 202
        assert run.await_count == 2

    def test_invalid_payload_is_422_without_spending(self) -> None:
        with (
            patch(
                "opspilot.api.routes.intake.run_ticket", new=AsyncMock(return_value=_OK_RUN)
            ) as run,
            TestClient(_app()) as client,
        ):
            res = client.post("/api/intake", json={"input": {}})  # missing key
        assert res.status_code == 422
        assert run.await_count == 0
