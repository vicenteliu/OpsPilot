"""Work-item intake — normalize, dedupe, run, comment write-back (ADR-0013).

All HTTP is faked with httpx.MockTransport; no live JSM or OpsPilot API is
contacted. The replay fixtures under tests/fixtures/jsm_replay/ are the same
ones `opspilot source jsm --replay` uses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from opspilot.intake import (
    IntakeLoop,
    OpsPilotRunClient,
    ReplayTransport,
    normalize_issue,
    render_comment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "jsm_replay"


# ── normalize_issue ────────────────────────────────────────────────────────


def _issue(key: str, issuetype: str, summary: str = "s", description: str = "d") -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "description": description,
            "issuetype": {"name": issuetype},
        },
    }


class TestNormalizeIssue:
    def test_incident_type_declared(self) -> None:
        item = normalize_issue(_issue("IT-1", "[System] Incident"))
        assert item.key == "IT-1"
        assert item.work_item["ticket_id"] == "IT-1"
        assert item.work_item["work_item_type"] == "incident"

    def test_service_request_type_declared(self) -> None:
        item = normalize_issue(_issue("IT-2", "Service Request"))
        assert item.work_item["work_item_type"] == "service_request"

    def test_unknown_type_left_undeclared_for_classification(self) -> None:
        item = normalize_issue(_issue("IT-3", "Task"))
        assert "work_item_type" not in item.work_item

    def test_subject_and_body_mapped(self) -> None:
        item = normalize_issue(_issue("IT-4", "Task", summary="VPN down", description="details"))
        assert item.work_item["subject"] == "VPN down"
        assert item.work_item["body"] == "details"


# ── OpsPilotRunClient ──────────────────────────────────────────────────────


class TestRunClient:
    def test_posts_input_with_bearer(self) -> None:
        capture: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            capture["path"] = request.url.path
            capture["headers"] = dict(request.headers)
            capture["body"] = json.loads(request.content)
            return httpx.Response(200, json={"session_id": "ses_1", "schema_valid": True})

        client = OpsPilotRunClient(
            api_url="http://api.test",
            api_token="tok-123",
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        res = client.run({"ticket_id": "IT-1", "subject": "s", "body": "b"})
        assert res["session_id"] == "ses_1"
        assert capture["path"] == "/api/run"
        assert capture["headers"]["authorization"] == "Bearer tok-123"
        assert capture["body"] == {"input": {"ticket_id": "IT-1", "subject": "s", "body": "b"}}


# ── IntakeLoop over the replay transport ───────────────────────────────────


_OK = {
    "session_id": "ses_ok",
    "artifact_id": "art_1",
    "schema_valid": True,
    "result": {
        "summary": "Multiple users cannot authenticate to the VPN.",
        "severity_suggested": "P2",
        "tasks": [
            {"ref": "task-1", "action": "Check RADIUS", "rationale": "auth path", "tier": "L2"}
        ],
        "citations": [{"id": "kb-1", "chunk_id": "chk_1", "source_path": "kb/vpn.md"}],
    },
    "error": None,
}


class FakeRunClient:
    """Stands in for OpsPilotRunClient; response keyed by ticket_id."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[str] = []

    def run(self, work_item: dict[str, Any]) -> dict[str, Any]:
        key = str(work_item["ticket_id"])
        self.calls.append(key)
        return self._responses.get(key, dict(_OK))


class TestIntakeLoop:
    def test_replay_end_to_end_with_dedupe(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        fake = FakeRunClient()
        report = IntakeLoop(ReplayTransport(FIXTURES, out), fake).run_once()  # type: ignore[arg-type]
        # IT-101 appears twice in the fixtures but runs exactly once.
        assert fake.calls == ["IT-101", "IT-102", "IT-103"]
        assert report.commented == ["IT-101", "IT-102", "IT-103"]
        assert ("IT-101", "duplicate") in report.skipped
        for key in ("IT-101", "IT-102", "IT-103"):
            assert (out / f"{key}.md").exists()

    def test_error_and_confirmation_produce_no_comment(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        fake = FakeRunClient(
            {
                "IT-101": {"session_id": "", "schema_valid": False, "error": "provider down"},
                "IT-102": {
                    "session_id": "",
                    "schema_valid": False,
                    "error": None,
                    "needs_confirmation": True,
                    "classification": {"confidence": 0.4},
                },
            }
        )
        report = IntakeLoop(ReplayTransport(FIXTURES, out), fake).run_once()  # type: ignore[arg-type]
        assert report.commented == ["IT-103"]
        assert any(k == "IT-101" and "provider down" in r for k, r in report.skipped)
        assert any(k == "IT-102" and "confirmation" in r for k, r in report.skipped)
        assert not (out / "IT-101.md").exists()
        assert not (out / "IT-102.md").exists()

    def test_run_exception_skips_item_and_continues(self, tmp_path: Path) -> None:
        class Boom(FakeRunClient):
            def run(self, work_item: dict[str, Any]) -> dict[str, Any]:
                if work_item["ticket_id"] == "IT-101":
                    raise RuntimeError("connection refused")
                return super().run(work_item)

        out = tmp_path / "out"
        report = IntakeLoop(ReplayTransport(FIXTURES, out), Boom()).run_once()  # type: ignore[arg-type]
        assert report.commented == ["IT-102", "IT-103"]
        assert any("connection refused" in reason for _, reason in report.skipped)


# ── render_comment ─────────────────────────────────────────────────────────


class TestRenderComment:
    def test_incident_artifact_rendered(self) -> None:
        body = render_comment(_OK["result"], session_id="ses_ok")  # type: ignore[arg-type]
        assert body.startswith("## OpsPilot suggestion")
        assert "Multiple users cannot authenticate" in body
        assert "**Suggested severity:** P2" in body
        assert "`L2` Check RADIUS" in body
        assert "kb/vpn.md" in body
        assert "ses_ok" in body
        assert "Advisory only" in body

    def test_request_artifact_rendered(self) -> None:
        body = render_comment(
            {
                "summary": "Provision VPN access.",
                "requested_item": "VPN access for a new starter",
                "approval_needed": True,
                "tasks": [
                    {
                        "ref": "task-1",
                        "action": "Create account",
                        "rationale": "per SOP",
                        "tier": "L1",
                        "citations": ["kb-1"],
                    }
                ],
            },
            session_id="ses_req",
        )
        assert "**Requested item:** VPN access for a new starter" in body
        assert "**Approval needed:** yes" in body
        assert "_[kb-1]_" in body
