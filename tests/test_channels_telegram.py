"""Telegram Channel adapter (assist mode) — allowlist, polling, replies.

All HTTP is faked with httpx.MockTransport; no live Telegram or OpsPilot
API is contacted. See docs/adr/0012 for the long-polling decision.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from opspilot.channels.base import OpsPilotChatClient
from opspilot.channels.telegram import TelegramChannel, TelegramConfig, split_reply

# ── OpsPilotChatClient (SSE parsing) ───────────────────────────────────────


def _sse_response(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in events)


def _chat_client(sse_body: str, capture: dict[str, Any]) -> OpsPilotChatClient:
    def handler(request: httpx.Request) -> httpx.Response:
        capture["headers"] = dict(request.headers)
        capture["body"] = json.loads(request.content)
        return httpx.Response(200, text=sse_body)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return OpsPilotChatClient(api_url="http://api.test", api_token="tok-123", http=http)


class TestChatClient:
    def test_returns_result_content(self) -> None:
        capture: dict[str, Any] = {}
        client = _chat_client(
            _sse_response(
                [
                    ("status", {"message": "Searching…"}),
                    ("result", {"content": "The answer.", "usage": {}}),
                ]
            ),
            capture,
        )
        answer = client.ask([{"role": "user", "content": "hi"}])
        assert answer == "The answer."
        # Bearer token attached; messages forwarded verbatim.
        assert capture["headers"]["authorization"] == "Bearer tok-123"
        assert capture["body"]["messages"] == [{"role": "user", "content": "hi"}]

    def test_error_event_raises(self) -> None:
        client = _chat_client(_sse_response([("error", {"message": "boom"})]), {})
        with pytest.raises(RuntimeError, match="boom"):
            client.ask([{"role": "user", "content": "hi"}])


# ── TelegramChannel ────────────────────────────────────────────────────────


def _update(chat_id: int, text: str, update_id: int = 1) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {"chat": {"id": chat_id}, "text": text},
    }


class FakeChat:
    """Stands in for OpsPilotChatClient; records what it was asked."""

    def __init__(self, answer: str = "kb answer") -> None:
        self.answer = answer
        self.calls: list[list[dict[str, str]]] = []

    def ask(self, messages: list[dict[str, str]]) -> str:
        self.calls.append([dict(m) for m in messages])
        return self.answer


def _channel(fake: FakeChat, sent: list[dict[str, Any]]) -> TelegramChannel:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sendMessage"):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {}})
        raise AssertionError(f"unexpected call: {request.url}")

    cfg = TelegramConfig(bot_token="t0k", allowed_chat_ids=frozenset({42}))
    return TelegramChannel(
        cfg,
        chat_client=fake,  # type: ignore[arg-type]
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


class TestTelegramChannel:
    def test_allowlisted_message_answered(self) -> None:
        fake, sent = FakeChat("route to L2"), []
        ch = _channel(fake, sent)
        ch.handle_update(_update(42, "VPN auth fails"))
        assert fake.calls[0][-1] == {"role": "user", "content": "VPN auth fails"}
        assert sent[0]["chat_id"] == 42
        assert sent[0]["text"] == "route to L2"

    def test_unknown_chat_ignored_silently(self) -> None:
        fake, sent = FakeChat(), []
        ch = _channel(fake, sent)
        ch.handle_update(_update(999, "let me in"))
        assert fake.calls == []
        assert sent == []

    def test_history_accumulates_and_reset_clears(self) -> None:
        fake, sent = FakeChat(), []
        ch = _channel(fake, sent)
        ch.handle_update(_update(42, "first"))
        ch.handle_update(_update(42, "second"))
        # Second ask carries first turn + its answer as history.
        assert [m["content"] for m in fake.calls[1]] == ["first", "kb answer", "second"]
        ch.handle_update(_update(42, "/reset"))
        ch.handle_update(_update(42, "third"))
        assert [m["content"] for m in fake.calls[2]] == ["third"]

    def test_start_command_replies_greeting_without_llm(self) -> None:
        fake, sent = FakeChat(), []
        ch = _channel(fake, sent)
        ch.handle_update(_update(42, "/start"))
        assert fake.calls == []
        assert sent and "OpsPilot" in sent[0]["text"]

    def test_chat_error_reported_to_user(self) -> None:
        class Boom:
            def ask(self, messages: list[dict[str, str]]) -> str:
                raise RuntimeError("provider down")

        sent: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {}})

        cfg = TelegramConfig(bot_token="t0k", allowed_chat_ids=frozenset({42}))
        ch = TelegramChannel(
            cfg,
            chat_client=Boom(),  # type: ignore[arg-type]
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        ch.handle_update(_update(42, "hello"))
        assert sent and "provider down" in sent[0]["text"]


class TestTelegramIntake:
    """/intake, /incident, /request file a Work item and reply (ADR-0014)."""

    _OK_RUN: dict[str, Any] = {
        "session_id": "ses_tg",
        "schema_valid": True,
        "error": None,
        "result": {
            "summary": "Multiple users cannot authenticate to the VPN.",
            "severity_suggested": "P2",
            "tasks": [
                {"ref": "task-1", "action": "Check RADIUS", "rationale": "auth", "tier": "L2"}
            ],
            "citations": [],
        },
    }

    class FakeRun:
        def __init__(self, response: dict[str, Any] | None = None) -> None:
            self.calls: list[dict[str, Any]] = []
            self._response = response

        def run(self, work_item: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(dict(work_item))
            return self._response or TestTelegramIntake._OK_RUN

    def _channel(
        self, run: FakeRun, sent: list[dict[str, Any]], chat: FakeChat | None = None
    ) -> TelegramChannel:
        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {}})

        cfg = TelegramConfig(bot_token="t0k", allowed_chat_ids=frozenset({42}))
        return TelegramChannel(
            cfg,
            chat_client=chat or FakeChat(),  # type: ignore[arg-type]
            http=httpx.Client(transport=httpx.MockTransport(handler)),
            run_client=run,  # type: ignore[arg-type]
        )

    def _intake_update(self, text: str, message_id: int = 7) -> dict[str, Any]:
        return {
            "update_id": 1,
            "message": {"chat": {"id": 42}, "message_id": message_id, "text": text},
        }

    def test_intake_runs_and_replies_suggestion(self) -> None:
        run = self.FakeRun()
        sent: list[dict[str, Any]] = []
        ch = self._channel(run, sent)
        ch.handle_update(self._intake_update("/intake VPN is down for everyone\nsince 09:10"))
        wi = run.calls[0]
        assert wi["ticket_id"] == "TG-42-7"
        assert wi["subject"] == "VPN is down for everyone"
        assert wi["body"] == "VPN is down for everyone\nsince 09:10"
        assert "work_item_type" not in wi  # Classification decides
        # Ack first, then the rendered suggestion.
        assert "one moment" in sent[0]["text"]
        assert "## OpsPilot suggestion" in sent[1]["text"]
        assert "`L2` Check RADIUS" in sent[1]["text"]
        assert "ses_tg" in sent[1]["text"]

    def test_incident_and_request_declare_type(self) -> None:
        run = self.FakeRun()
        sent: list[dict[str, Any]] = []
        ch = self._channel(run, sent)
        ch.handle_update(self._intake_update("/incident VPN down"))
        ch.handle_update(self._intake_update("/request need VPN access"))
        assert run.calls[0]["work_item_type"] == "incident"
        assert run.calls[1]["work_item_type"] == "service_request"

    def test_needs_confirmation_asks_for_explicit_type(self) -> None:
        run = self.FakeRun(
            {
                "session_id": "",
                "schema_valid": False,
                "error": None,
                "needs_confirmation": True,
                "classification": {"confidence": 0.4},
            }
        )
        sent: list[dict[str, Any]] = []
        ch = self._channel(run, sent)
        ch.handle_update(self._intake_update("/intake cannot access X"))
        assert "/incident" in sent[-1]["text"]
        assert "suggestion" not in sent[-1]["text"]

    def test_empty_text_gives_usage_hint_without_run(self) -> None:
        run = self.FakeRun()
        sent: list[dict[str, Any]] = []
        ch = self._channel(run, sent)
        ch.handle_update(self._intake_update("/intake"))
        assert run.calls == []
        assert "Usage: /intake" in sent[0]["text"]

    def test_run_error_reported(self) -> None:
        run = self.FakeRun({"session_id": "", "schema_valid": False, "error": "provider down"})
        sent: list[dict[str, Any]] = []
        ch = self._channel(run, sent)
        ch.handle_update(self._intake_update("/intake VPN down"))
        assert "provider down" in sent[-1]["text"]

    def test_plain_message_still_goes_to_chat(self) -> None:
        run = self.FakeRun()
        sent: list[dict[str, Any]] = []
        chat = FakeChat("kb answer")
        ch = self._channel(run, sent, chat=chat)
        ch.handle_update(self._intake_update("what is our VPN SOP?"))
        assert run.calls == []
        assert chat.calls  # chat path untouched

    def test_unknown_chat_still_dropped(self) -> None:
        run = self.FakeRun()
        sent: list[dict[str, Any]] = []
        ch = self._channel(run, sent)
        ch.handle_update(
            {"update_id": 1, "message": {"chat": {"id": 999}, "message_id": 1, "text": "/intake x"}}
        )
        assert run.calls == []
        assert sent == []


class TestSplitReply:
    def test_short_reply_single_chunk(self) -> None:
        assert split_reply("hi") == ["hi"]

    def test_long_reply_chunked_at_limit(self) -> None:
        chunks = split_reply("x" * 9000)
        assert [len(c) for c in chunks] == [4096, 4096, 808]

    def test_empty_reply_placeholder(self) -> None:
        assert split_reply("") == ["(empty response)"]
