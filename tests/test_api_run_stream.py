"""Tests for POST /api/run/stream (SSE streaming endpoint)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.run import router as run_router
from opspilot.config import Config
from opspilot.orchestrator.types import RunResult, TokenUsage

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SAMPLE_TICKET = {
    "ticket_id": "TKT-002",
    "channel": "slack",
    "submitted_at": "2026-05-06T09:00:00Z",
    "subject": "DB connection pool exhausted",
    "body": "All 50 connections in use, new requests timing out.",
    # Declared type → stream goes straight to the incident playbook (no classify).
    "work_item_type": "incident",
}

_MOCK_SUMMARY = {
    "schema_version": "ticket_summary_v1",
    "ticket_ref": "TKT-002",
    "summary": "DB connection pool exhausted",
    "symptoms": ["Connection timeout"],
    "scope": "production",
    "tried_steps": [],
    "missing_fields": [],
    "next_actions": [],
    "severity_suggested": "P1",
    "citations": [],
}


def _make_run_result(*, error: str | None = None) -> RunResult:
    return RunResult(
        session_id="sess_stream_01",
        artifact_id="art_stream_01" if error is None else None,
        summary=_MOCK_SUMMARY if error is None else {},
        schema_valid=error is None,
        error=error,
        usage=TokenUsage(input_tokens=100, output_tokens=200, cost_usd=0.0012),
    )


def _make_test_app() -> FastAPI:
    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = MagicMock(spec=Config)
        cfg.ui_modules = {"run": True}
        app.state.cfg = cfg
        app.state.active_model_ref = "ollama-local/gemma4:e4b@2026-04"
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

    app = FastAPI(lifespan=test_lifespan)
    app.include_router(run_router, prefix="/api")
    return app


def _parse_sse(raw: str) -> list[dict]:
    """Parse raw SSE text into a list of {type, data} dicts."""
    events = []
    current_event = "message"
    for line in raw.splitlines():
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            events.append({"type": current_event, "data": json.loads(line[6:])})
            current_event = "message"
    return events


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestRunStreamSuccess:
    def test_status_200(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                assert resp.status_code == 200

    def test_content_type_is_event_stream(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                assert "text/event-stream" in resp.headers["content-type"]

    def test_result_event_emitted(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        result_events = [e for e in events if e["type"] == "result"]
        assert len(result_events) == 1

    def test_result_payload_session_id(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        result_event = next(e for e in events if e["type"] == "result")
        assert result_event["data"]["session_id"] == "sess_stream_01"

    def test_result_payload_artifact_id(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        result_event = next(e for e in events if e["type"] == "result")
        assert result_event["data"]["artifact_id"] == "art_stream_01"

    def test_result_payload_summary_fields(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        result_event = next(e for e in events if e["type"] == "result")
        assert result_event["data"]["result"]["ticket_ref"] == "TKT-002"
        assert result_event["data"]["result"]["severity_suggested"] == "P1"

    def test_result_payload_no_error(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        result_event = next(e for e in events if e["type"] == "result")
        assert result_event["data"]["error"] is None

    def test_result_payload_usage(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        result_event = next(e for e in events if e["type"] == "result")
        usage = result_event["data"]["usage"]
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 200
        assert usage["cost_usd"] == pytest.approx(0.0012)

    def test_no_error_event_on_success(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        assert not any(e["type"] == "error" for e in events)

    def test_status_events_emitted_by_on_progress(self) -> None:
        """on_progress calls inside run_ticket_summary must appear as status events."""
        progress_messages = ["Session created", "Calling LLM…", "Finalizing"]

        def fake_run(request, *, on_progress=None, **kwargs):  # noqa: ANN001
            if on_progress:
                for msg in progress_messages:
                    on_progress(msg)
            return _make_run_result()

        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", side_effect=fake_run),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        status_messages = [e["data"]["message"] for e in events if e["type"] == "status"]
        assert status_messages == progress_messages

    def test_status_events_precede_result_event(self) -> None:
        def fake_run(request, *, on_progress=None, **kwargs):  # noqa: ANN001
            if on_progress:
                on_progress("step 1")
                on_progress("step 2")
            return _make_run_result()

        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", side_effect=fake_run),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        types = [e["type"] for e in events]
        # all status events come before the result event
        result_idx = types.index("result")
        assert all(t == "status" for t in types[:result_idx])


# ---------------------------------------------------------------------------
# Error path — orchestrator raises
# ---------------------------------------------------------------------------


class TestRunStreamError:
    def test_error_event_emitted_on_exception(self) -> None:
        app = _make_test_app()

        with (
            patch(
                "opspilot.api.routes.run.run_ticket_summary",
                side_effect=RuntimeError("provider timeout"),
            ),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert "provider timeout" in error_events[0]["data"]["message"]

    def test_no_result_event_on_exception(self) -> None:
        app = _make_test_app()

        with (
            patch(
                "opspilot.api.routes.run.run_ticket_summary",
                side_effect=RuntimeError("provider timeout"),
            ),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        assert not any(e["type"] == "result" for e in events)

    def test_error_event_when_run_result_has_error(self) -> None:
        """RunResult.error (orchestrator-level error) still emits a result event, not error event."""
        run_result = _make_run_result(error="schema validation failed")
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        # orchestrator error surfaces inside the result payload, not as an SSE error event
        result_event = next(e for e in events if e["type"] == "result")
        assert result_event["data"]["error"] == "schema validation failed"
        assert not any(e["type"] == "error" for e in events)

    def test_status_200_even_on_exception(self) -> None:
        """HTTP status is always 200; errors are in the SSE stream."""
        app = _make_test_app()

        with (
            patch(
                "opspilot.api.routes.run.run_ticket_summary",
                side_effect=RuntimeError("boom"),
            ),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Event format
# ---------------------------------------------------------------------------


class TestRunStreamEventFormat:
    def test_each_event_has_type_field(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        assert len(events) >= 1
        for event in events:
            assert event["type"] in ("status", "result", "error")

    def test_status_event_has_message_field(self) -> None:
        def fake_run(request, *, on_progress=None, **kwargs):  # noqa: ANN001
            if on_progress:
                on_progress("hello")
            return _make_run_result()

        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", side_effect=fake_run),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        status_events = [e for e in events if e["type"] == "status"]
        assert len(status_events) == 1
        assert status_events[0]["data"]["message"] == "hello"

    def test_result_event_has_required_keys(self) -> None:
        run_result = _make_run_result()
        app = _make_test_app()

        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=run_result),
            TestClient(app) as client,
        ):
            with client.stream("POST", "/api/run/stream", json={"input": _SAMPLE_TICKET}) as resp:
                body = resp.read().decode()

        events = _parse_sse(body)
        result_event = next(e for e in events if e["type"] == "result")
        data = result_event["data"]
        for key in ("session_id", "artifact_id", "schema_valid", "result", "error", "usage"):
            assert key in data, f"missing key: {key}"


