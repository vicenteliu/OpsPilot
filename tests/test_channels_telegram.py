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


class TestSplitReply:
    def test_short_reply_single_chunk(self) -> None:
        assert split_reply("hi") == ["hi"]

    def test_long_reply_chunked_at_limit(self) -> None:
        chunks = split_reply("x" * 9000)
        assert [len(c) for c in chunks] == [4096, 4096, 808]

    def test_empty_reply_placeholder(self) -> None:
        assert split_reply("") == ["(empty response)"]
