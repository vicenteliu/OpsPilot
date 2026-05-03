"""Tests for ``opspilot.providers.anthropic``.

All tests use ``unittest.mock.patch`` to avoid hitting the real Anthropic API.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from opspilot.errors import ProviderError
from opspilot.providers import AnthropicProvider, Message, SamplingParams, ToolCall, ToolDef
from opspilot.providers.base import ProviderProtocol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_response(text: str, input_tokens: int = 10, output_tokens: int = 5) -> MagicMock:
    """Build a mock Anthropic Messages response with a single text block."""
    block = SimpleNamespace(type="text", text=text)
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    resp.usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


def _make_tool_use_response(
    tool_id: str,
    tool_name: str,
    tool_input: dict,  # type: ignore[type-arg]
) -> MagicMock:
    """Build a mock Anthropic Messages response with a tool_use block."""
    block = SimpleNamespace(type="tool_use", id=tool_id, name=tool_name, input=tool_input)
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "tool_use"
    resp.usage = SimpleNamespace(input_tokens=20, output_tokens=8)
    return resp


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_anthropic_satisfies_protocol(self) -> None:
        with patch("opspilot.providers.anthropic.Anthropic"):
            p = AnthropicProvider(api_key="sk-test")
            assert isinstance(p, ProviderProtocol)


# ---------------------------------------------------------------------------
# Test: basic text response
# ---------------------------------------------------------------------------


class TestChatReturnsTextResponse:
    def test_chat_returns_text_response(self) -> None:
        mock_response = _make_text_response("Hello from Claude")

        with patch("opspilot.providers.anthropic.Anthropic") as mock_cls:
            instance = mock_cls.return_value
            instance.messages.create.return_value = mock_response

            provider = AnthropicProvider(api_key="sk-test")
            resp = provider.chat(
                [Message(role="user", content="Hello")],
                model="claude-sonnet-4-6",
                params=SamplingParams(),
            )

        assert resp.content == "Hello from Claude"
        assert resp.finish_reason == "stop"
        assert resp.tool_calls is None
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5
        # Cost: (10 * 3 + 5 * 15) / 1_000_000
        expected_cost = (10 * 3 + 5 * 15) / 1_000_000
        assert abs(resp.usage.cost_usd - expected_cost) < 1e-10


# ---------------------------------------------------------------------------
# Test: tool call response
# ---------------------------------------------------------------------------


class TestChatReturnsToolCall:
    def test_chat_returns_tool_call(self) -> None:
        mock_response = _make_tool_use_response("toolu_01abc", "kb_search", {"query": "VPN auth"})

        with patch("opspilot.providers.anthropic.Anthropic") as mock_cls:
            instance = mock_cls.return_value
            instance.messages.create.return_value = mock_response

            provider = AnthropicProvider(api_key="sk-test")
            resp = provider.chat(
                [Message(role="user", content="Search for VPN auth")],
                model="claude-sonnet-4-6",
                params=SamplingParams(),
                tools=[
                    ToolDef(
                        name="kb_search",
                        description="Search the KB",
                        parameters={
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    )
                ],
            )

        assert resp.finish_reason == "tool_call"
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        tc = resp.tool_calls[0]
        assert isinstance(tc, ToolCall)
        assert tc.id == "toolu_01abc"
        assert tc.name == "kb_search"
        assert tc.arguments == {"query": "VPN auth"}


# ---------------------------------------------------------------------------
# Test: system message extracted into top-level param
# ---------------------------------------------------------------------------


class TestChatExtractsSystemMessage:
    def test_chat_extracts_system_message(self) -> None:
        mock_response = _make_text_response("ok")
        captured_kwargs: dict = {}  # type: ignore[type-arg]

        with patch("opspilot.providers.anthropic.Anthropic") as mock_cls:
            instance = mock_cls.return_value

            def capture(**kwargs: object) -> MagicMock:
                captured_kwargs.update(kwargs)
                return mock_response

            instance.messages.create.side_effect = capture

            provider = AnthropicProvider(api_key="sk-test")
            provider.chat(
                [
                    Message(role="system", content="You are a helpful assistant."),
                    Message(role="user", content="Hello"),
                ],
                model="claude-sonnet-4-6",
                params=SamplingParams(),
            )

        assert captured_kwargs["system"] == "You are a helpful assistant."
        # System messages must not appear in the messages list.
        roles = [m["role"] for m in captured_kwargs["messages"]]
        assert "system" not in roles


# ---------------------------------------------------------------------------
# Test: tool messages converted to tool_result blocks
# ---------------------------------------------------------------------------


class TestChatConvertsToolMessages:
    def test_chat_converts_tool_messages(self) -> None:
        mock_response = _make_text_response("done")
        captured_kwargs: dict = {}  # type: ignore[type-arg]

        with patch("opspilot.providers.anthropic.Anthropic") as mock_cls:
            instance = mock_cls.return_value

            def capture(**kwargs: object) -> MagicMock:
                captured_kwargs.update(kwargs)
                return mock_response

            instance.messages.create.side_effect = capture

            provider = AnthropicProvider(api_key="sk-test")
            provider.chat(
                [
                    Message(role="user", content="search please"),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(id="toolu_01", name="kb_search", arguments={"query": "x"})
                        ],
                    ),
                    Message(
                        role="tool",
                        content='{"hits":[]}',
                        tool_call_id="toolu_01",
                        name="kb_search",
                    ),
                ],
                model="claude-sonnet-4-6",
                params=SamplingParams(),
            )

        messages = captured_kwargs["messages"]
        # Last message should be a user message with tool_result content.
        last = messages[-1]
        assert last["role"] == "user"
        assert isinstance(last["content"], list)
        assert last["content"][0]["type"] == "tool_result"
        assert last["content"][0]["tool_use_id"] == "toolu_01"
        assert last["content"][0]["content"] == '{"hits":[]}'

    def test_consecutive_tool_messages_batched(self) -> None:
        """Two consecutive tool messages must be batched into one user turn."""
        mock_response = _make_text_response("done")
        captured_kwargs: dict = {}  # type: ignore[type-arg]

        with patch("opspilot.providers.anthropic.Anthropic") as mock_cls:
            instance = mock_cls.return_value

            def capture(**kwargs: object) -> MagicMock:
                captured_kwargs.update(kwargs)
                return mock_response

            instance.messages.create.side_effect = capture

            provider = AnthropicProvider(api_key="sk-test")
            provider.chat(
                [
                    Message(role="user", content="go"),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(id="t1", name="kb_search", arguments={}),
                            ToolCall(id="t2", name="kb_search", arguments={}),
                        ],
                    ),
                    Message(role="tool", content="r1", tool_call_id="t1"),
                    Message(role="tool", content="r2", tool_call_id="t2"),
                ],
                model="claude-sonnet-4-6",
                params=SamplingParams(),
            )

        messages = captured_kwargs["messages"]
        # Should be: user, assistant, user(2 tool results)
        user_turns = [m for m in messages if m["role"] == "user"]
        # Last user turn has both tool results batched.
        last_user = user_turns[-1]
        assert isinstance(last_user["content"], list)
        tool_results = [b for b in last_user["content"] if b["type"] == "tool_result"]
        assert len(tool_results) == 2


# ---------------------------------------------------------------------------
# Test: embed raises ProviderError
# ---------------------------------------------------------------------------


class TestEmbedRaisesNotSupported:
    def test_embed_raises_not_supported(self) -> None:
        with patch("opspilot.providers.anthropic.Anthropic"):
            provider = AnthropicProvider(api_key="sk-test")

        with pytest.raises(ProviderError, match="does not support embeddings"):
            provider.embed(["hello"], model="some-model")


# ---------------------------------------------------------------------------
# Test: missing API key raises ProviderError
# ---------------------------------------------------------------------------


class TestMissingApiKeyRaises:
    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with (
            patch("opspilot.providers.anthropic.Anthropic"),
            pytest.raises(ProviderError, match="API key not found"),
        ):
            AnthropicProvider(api_key=None)
