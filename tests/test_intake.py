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
import pytest

from opspilot.intake import (
    IntakeLoop,
    IntakeState,
    JsmTransport,
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

    def test_playbook_and_model_passthrough(self) -> None:
        capture: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            capture["body"] = json.loads(request.content)
            return httpx.Response(200, json={"session_id": "ses_1", "schema_valid": True})

        client = OpsPilotRunClient(
            api_url="http://api.test",
            http=httpx.Client(transport=httpx.MockTransport(handler)),
            playbook_id="pb_ticket_summary_en",
            model_id="anthropic/claude-haiku-4-5-20251001",
        )
        client.run({"ticket_id": "IT-1", "subject": "s", "body": "b"})
        assert capture["body"]["playbook_id"] == "pb_ticket_summary_en"
        assert capture["body"]["model_id"] == "anthropic/claude-haiku-4-5-20251001"


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


# ── JsmTransport (live polling, #57) ───────────────────────────────────────


class TestJsmTransport:
    _JQL = 'project = IT AND status = "Open"'

    def _transport(self, handler: Any, page_size: int = 50) -> JsmTransport:
        return JsmTransport(
            base_url="https://example.atlassian.net",
            email="ops@example.com",
            api_token="jsm-tok",
            jql=self._JQL,
            http=httpx.Client(transport=httpx.MockTransport(handler)),
            page_size=page_size,
        )

    def test_jql_scope_and_auth_sent(self) -> None:
        capture: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            capture["path"] = request.url.path
            capture["params"] = dict(request.url.params)
            capture["auth"] = request.headers.get("authorization", "")
            return httpx.Response(
                200, json={"issues": [_issue("IT-1", "[System] Incident")], "total": 1}
            )

        items = self._transport(handler).fetch_new()
        assert capture["path"] == "/rest/api/2/search"
        # The JQL filter is the scope: sent verbatim on every request.
        assert capture["params"]["jql"] == self._JQL
        assert capture["auth"].startswith("Basic ")
        assert [i.key for i in items] == ["IT-1"]
        assert items[0].work_item["work_item_type"] == "incident"

    def test_paginates_past_one_page(self) -> None:
        starts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            start = int(request.url.params["startAt"])
            starts.append(start)
            if start == 0:
                issues = [_issue("IT-1", "Task"), _issue("IT-2", "Task")]
            else:
                issues = [_issue("IT-3", "Task")]
            return httpx.Response(200, json={"issues": issues, "total": 3})

        items = self._transport(handler, page_size=2).fetch_new()
        assert [i.key for i in items] == ["IT-1", "IT-2", "IT-3"]
        assert starts == [0, 2]

    def test_http_error_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"errorMessages": ["bad credentials"]})

        with pytest.raises(httpx.HTTPStatusError):
            self._transport(handler).fetch_new()

    def test_comment_posted_to_issue(self) -> None:
        posted: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"comments": []})
            posted.append(json.loads(request.content))
            assert request.url.path == "/rest/api/2/issue/IT-9/comment"
            return httpx.Response(201, json={"id": "10001"})

        self._transport(handler).post_comment("IT-9", "suggestion body", "ses_abc")
        assert posted == [{"body": "suggestion body"}]

    def test_existing_marker_skips_post(self) -> None:
        posted: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={"comments": [{"body": "old text … (session `ses_abc`) …"}]},
                )
            posted.append(request.url.path)
            return httpx.Response(201, json={})

        self._transport(handler).post_comment("IT-9", "suggestion body", "ses_abc")
        # Marker already on the issue → no POST issued, no duplicate comment.
        assert posted == []

    def test_post_error_raises_for_retry_queue(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"comments": []})
            return httpx.Response(502, json={})

        with pytest.raises(httpx.HTTPStatusError):
            self._transport(handler).post_comment("IT-9", "body", "ses_abc")


# ── IntakeLoop.run_forever ─────────────────────────────────────────────────


class TestRunForever:
    def test_failed_pass_retries_instead_of_crashing(self) -> None:
        class FlakyTransport:
            def __init__(self) -> None:
                self.calls = 0

            def fetch_new(self) -> list[Any]:
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("JSM down")
                raise KeyboardInterrupt

            def post_comment(self, key: str, body: str, marker: str) -> None:
                raise AssertionError("nothing to comment")

        transport = FlakyTransport()
        loop = IntakeLoop(transport, FakeRunClient())  # type: ignore[arg-type]
        with pytest.raises(KeyboardInterrupt):
            loop.run_forever(0)
        # First pass failed (outage) → logged and retried, not crashed.
        assert transport.calls == 2


# ── IntakeState (persistence, #58) ─────────────────────────────────────────


class TestIntakeState:
    def test_marked_keys_survive_restart(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        IntakeState(path).mark("IT-1")
        fresh = IntakeState(path)  # fresh instance = adapter restart
        assert fresh.has("IT-1")
        assert not fresh.has("IT-2")

    def test_forget_enables_rerun(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        st = IntakeState(path)
        st.mark("IT-1")
        assert st.forget("IT-1") is True
        assert st.forget("IT-1") is False
        assert not IntakeState(path).has("IT-1")

    def test_memory_only_without_path(self) -> None:
        st = IntakeState()
        st.mark("IT-1")
        assert st.has("IT-1")


class TestIntakeLoopPersistence:
    def test_restart_does_not_rerun_processed_keys(self, tmp_path: Path) -> None:
        path, out = tmp_path / "state.json", tmp_path / "out"
        first = FakeRunClient()
        IntakeLoop(ReplayTransport(FIXTURES, out), first, state=IntakeState(path)).run_once()  # type: ignore[arg-type]
        assert first.calls == ["IT-101", "IT-102", "IT-103"]
        second = FakeRunClient()
        report = IntakeLoop(
            ReplayTransport(FIXTURES, out),
            second,  # type: ignore[arg-type]
            state=IntakeState(path),
        ).run_once()
        assert second.calls == []
        assert report.commented == []

    def test_failed_run_not_marked_and_retries_next_pass(self, tmp_path: Path) -> None:
        path, out = tmp_path / "state.json", tmp_path / "out"

        class Boom(FakeRunClient):
            def run(self, work_item: dict[str, Any]) -> dict[str, Any]:
                if work_item["ticket_id"] == "IT-101":
                    raise RuntimeError("connection refused")
                return super().run(work_item)

        IntakeLoop(ReplayTransport(FIXTURES, out), Boom(), state=IntakeState(path)).run_once()  # type: ignore[arg-type]
        # Transient failure is not marked; deterministic outcomes are.
        assert not IntakeState(path).has("IT-101")
        assert IntakeState(path).has("IT-102")
        retry = FakeRunClient()
        IntakeLoop(ReplayTransport(FIXTURES, out), retry, state=IntakeState(path)).run_once()  # type: ignore[arg-type]
        assert retry.calls == ["IT-101"]
        assert (out / "IT-101.md").exists()

    def test_failed_post_queued_and_flushed_without_rerunning_llm(self, tmp_path: Path) -> None:
        path, out = tmp_path / "state.json", tmp_path / "out"

        class FailOncePostTransport:
            """Fetches from replay fixtures; the first post attempt fails."""

            def __init__(self) -> None:
                self._inner = ReplayTransport(FIXTURES, out)
                self._failures = 1
                self.markers: list[str] = []

            def fetch_new(self) -> list[Any]:
                return self._inner.fetch_new()

            def post_comment(self, key: str, body: str, marker: str) -> None:
                if self._failures > 0:
                    self._failures -= 1
                    raise RuntimeError("JSM 502")
                self.markers.append(marker)
                self._inner.post_comment(key, body, marker)

        transport = FailOncePostTransport()
        first = FakeRunClient()
        r1 = IntakeLoop(transport, first, state=IntakeState(path)).run_once()  # type: ignore[arg-type]
        # IT-101's post failed → run is done (marked), comment queued.
        assert r1.commented == ["IT-102", "IT-103"]
        assert IntakeState(path).has("IT-101")
        assert "IT-101" in IntakeState(path).pending_comments()
        # Next pass flushes the queue; the LLM is NOT re-run.
        second = FakeRunClient()
        r2 = IntakeLoop(transport, second, state=IntakeState(path)).run_once()  # type: ignore[arg-type]
        assert second.calls == []
        assert r2.commented == ["IT-101"]
        assert transport.markers[0] == "ses_ok"  # session id doubles as idempotency marker
        assert (out / "IT-101.md").exists()
        assert IntakeState(path).pending_comments() == {}

    def test_forget_drops_queued_comment_too(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        st = IntakeState(path)
        st.queue_comment("IT-7", "body", "ses_x")
        assert st.forget("IT-7") is True
        assert IntakeState(path).pending_comments() == {}

    def test_forget_then_pass_reruns_only_that_key(self, tmp_path: Path) -> None:
        path, out = tmp_path / "state.json", tmp_path / "out"
        IntakeLoop(
            ReplayTransport(FIXTURES, out),
            FakeRunClient(),  # type: ignore[arg-type]
            state=IntakeState(path),
        ).run_once()
        st = IntakeState(path)
        assert st.forget("IT-102")
        rerun = FakeRunClient()
        IntakeLoop(ReplayTransport(FIXTURES, out), rerun, state=st).run_once()  # type: ignore[arg-type]
        assert rerun.calls == ["IT-102"]
