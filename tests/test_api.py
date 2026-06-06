"""Tests for the FastAPI routes.

Uses ``TestClient`` (synchronous) with mocked app.state to avoid touching
Ollama, Anthropic, SQLite, or LanceDB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.config import router as config_router
from opspilot.api.routes.run import router as run_router
from opspilot.config import Config
from opspilot.orchestrator.types import RunResult

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_MOCK_MODEL_REF = "ollama-local/gemma4:e4b@2026-04"

_SAMPLE_TICKET = {
    "ticket_id": "TKT-001",
    "channel": "email",
    "submitted_at": "2026-05-01T10:00:00Z",
    "subject": "VPN not connecting",
    "body": "Cannot connect to VPN since morning.",
    # Declared type → run goes straight to the incident playbook (no classify).
    "work_item_type": "incident",
}

_MOCK_SUMMARY = {
    "schema_version": "ticket_summary_v1",
    "ticket_ref": "TKT-001",
    "summary": "VPN connection failure",
    "symptoms": ["Cannot connect to VPN"],
    "scope": "single user",
    "tried_steps": [],
    "missing_fields": [],
    "next_actions": [],
    "severity_suggested": "P2",
    "citations": [],
}


def _make_test_app() -> FastAPI:
    """Build a FastAPI test app that injects mocks into app.state during lifespan."""

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = MagicMock(spec=Config)
        cfg.ui_modules = {"run": True}

        app.state.cfg = cfg
        app.state.active_model_ref = _MOCK_MODEL_REF
        app.state.playbook = MagicMock()
        app.state.sqlite = MagicMock()
        app.state.lance = MagicMock()
        app.state.chat_provider = MagicMock()
        app.state.embed_fn = lambda text: [0.0] * 768
        app.state.session_mgr = MagicMock()
        app.state.redactor = MagicMock()
        app.state.request_fulfillment_pb = MagicMock()
        app.state.classify_pb = MagicMock()
        app.state.classify_threshold = 0.7
        app.state.mcp_registry = None
        yield

    test_app = FastAPI(lifespan=test_lifespan)
    test_app.include_router(config_router, prefix="/api")
    test_app.include_router(run_router, prefix="/api")
    return test_app


# ---------------------------------------------------------------------------
# GET /api/config tests
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_get_config_returns_model_ref(self) -> None:
        with TestClient(_make_test_app()) as client:
            resp = client.get("/api/config")

        assert resp.status_code == 200
        data = resp.json()
        assert "active_model_ref" in data
        assert data["active_model_ref"] == _MOCK_MODEL_REF

    def test_get_config_returns_modules(self) -> None:
        with TestClient(_make_test_app()) as client:
            resp = client.get("/api/config")

        assert resp.status_code == 200
        data = resp.json()
        assert "modules" in data
        assert data["modules"]["run"] is True


# ---------------------------------------------------------------------------
# POST /api/run tests
# ---------------------------------------------------------------------------


def _make_run_result(*, error: str | None = None, schema_valid: bool = True) -> RunResult:
    return RunResult(
        session_id="sess_01",
        artifact_id="art_01" if error is None else None,
        summary=_MOCK_SUMMARY if error is None else {},
        schema_valid=schema_valid,
        error=error,
    )


class TestPostRun:
    def test_post_run_success(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch(
                "opspilot.api.routes.run.run_ticket_summary",
                return_value=run_result,
            ),
            TestClient(app) as client,
        ):
            resp = client.post("/api/run", json={"input": _SAMPLE_TICKET})

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess_01"
        assert data["artifact_id"] == "art_01"
        assert data["schema_valid"] is True
        assert data["error"] is None
        assert data["result"]["ticket_ref"] == "TKT-001"

    def test_post_run_error(self) -> None:
        run_result = _make_run_result(error="JSON parse error: ...", schema_valid=False)
        app = _make_test_app()

        with (
            patch(
                "opspilot.api.routes.run.run_ticket_summary",
                return_value=run_result,
            ),
            TestClient(app) as client,
        ):
            resp = client.post("/api/run", json={"input": _SAMPLE_TICKET})

        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is not None
        assert "JSON parse error" in data["error"]
        assert data["schema_valid"] is False
        assert data["result"] == {}


# ---------------------------------------------------------------------------
# Playbook selection (#5 — incident default vs service_request)
# ---------------------------------------------------------------------------


def test_resolve_playbook_selects_by_playbook_id() -> None:
    from pathlib import Path
    from types import SimpleNamespace

    from opspilot.api.routes.run import _resolve_provider_and_playbook
    from opspilot.api.types import ApiRunRequest
    from opspilot.orchestrator.types import load_playbook

    pb_dir = Path(__file__).resolve().parents[1] / "playbooks"
    incident = load_playbook(pb_dir / "pb_ticket_summary_zh")
    request = load_playbook(pb_dir / "pb_request_fulfillment_zh")
    state = SimpleNamespace(
        playbook=incident,
        request_fulfillment_pb=request,
        chat_provider=object(),
    )

    # No playbook_id → incident default.
    _, pb_default = _resolve_provider_and_playbook(ApiRunRequest(input={}), state)
    assert pb_default.id == "pb_ticket_summary_zh"

    # playbook_id selects the service-request playbook.
    _, pb_req = _resolve_provider_and_playbook(
        ApiRunRequest(input={}, playbook_id="pb_request_fulfillment_zh"), state
    )
    assert pb_req.id == "pb_request_fulfillment_zh"
    assert pb_req.output_schema == "request_fulfillment_v1"


# ---------------------------------------------------------------------------
# Classification routing (#6 — declared-first, classify on absence)
# ---------------------------------------------------------------------------


_UNTYPED_TICKET = {k: v for k, v in _SAMPLE_TICKET.items() if k != "work_item_type"}


class TestClassificationRouting:
    def test_high_confidence_auto_routes_and_runs(self) -> None:
        from opspilot.orchestrator.classify import ClassificationResult

        app = _make_test_app()
        cls = ClassificationResult("incident", 0.9, "service outage")
        with (
            patch("opspilot.api.routes.run.classify_work_item", return_value=cls) as mock_cls,
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_make_run_result()),
            TestClient(app) as client,
        ):
            resp = client.post("/api/run", json={"input": _UNTYPED_TICKET})

        assert resp.status_code == 200
        data = resp.json()
        assert mock_cls.called
        assert data["needs_confirmation"] is False
        assert data["classification"]["work_item_type"] == "incident"
        assert data["session_id"] == "sess_01"

    def test_low_confidence_returns_needs_confirmation_without_running(self) -> None:
        from opspilot.orchestrator.classify import ClassificationResult

        app = _make_test_app()
        cls = ClassificationResult("service_request", 0.4, "ambiguous ask")
        with (
            patch("opspilot.api.routes.run.classify_work_item", return_value=cls),
            patch("opspilot.api.routes.run.run_ticket_summary") as mock_run,
            TestClient(app) as client,
        ):
            resp = client.post("/api/run", json={"input": _UNTYPED_TICKET})

        assert resp.status_code == 200
        data = resp.json()
        assert data["needs_confirmation"] is True
        assert data["classification"]["confidence"] == 0.4
        assert data["session_id"] == ""
        assert data["result"] == {}
        mock_run.assert_not_called()

    def test_declared_type_skips_classification(self) -> None:
        app = _make_test_app()
        with (
            patch("opspilot.api.routes.run.classify_work_item") as mock_cls,
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_make_run_result()),
            TestClient(app) as client,
        ):
            resp = client.post("/api/run", json={"input": _SAMPLE_TICKET})

        assert resp.status_code == 200
        assert resp.json()["needs_confirmation"] is False
        mock_cls.assert_not_called()
