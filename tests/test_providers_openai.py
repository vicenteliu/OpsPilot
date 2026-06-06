"""Tests for ``opspilot.providers.openai_compat``.

All tests use ``unittest.mock.patch`` to avoid hitting real APIs.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from opspilot.errors import ProviderError
from opspilot.providers import Message, OpenAIProvider, SamplingParams, ToolCall, ToolDef
from opspilot.providers.base import ProviderProtocol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_choice(
    content: str = "",
    finish_reason: str = "stop",
    tool_calls: list | None = None,
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> MagicMock:
    """Build a mock openai ChatCompletion response."""
    msg = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=input_tokens, completion_tokens=output_tokens)
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_openai_tool_call(tc_id: str, name: str, arguments: dict) -> SimpleNamespace:  # type: ignore[type-arg]
    fn = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    return SimpleNamespace(id=tc_id, function=fn)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_openai_satisfies_protocol(self) -> None:
        with patch("opspilot.providers.openai_compat.OpenAI"):
            p = OpenAIProvider(provider_id="openai", api_key="sk-test")
            assert isinstance(p, ProviderProtocol)


# ---------------------------------------------------------------------------
# Test: basic text response
# ---------------------------------------------------------------------------


class TestChatReturnsTextResponse:
    def test_chat_returns_text_response(self) -> None:
        mock_response = _make_choice(content="Hello from GPT")

        with patch("opspilot.providers.openai_compat.OpenAI") as mock_cls:
            instance = mock_cls.return_value
            instance.chat.completions.create.return_value = mock_response

            provider = OpenAIProvider(provider_id="openai", api_key="sk-test")
            resp = provider.chat(
                [Message(role="user", content="Hello")],
                model="gpt-4o",
                params=SamplingParams(),
            )

        assert resp.content == "Hello from GPT"
        assert resp.finish_reason == "stop"
        assert resp.tool_calls is None
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5


# ---------------------------------------------------------------------------
# Test: tool call response
# ---------------------------------------------------------------------------


class TestChatReturnsToolCall:
    def test_chat_returns_tool_call(self) -> None:
        tc = _make_openai_tool_call("call_abc123", "kb_search", {"query": "VPN auth"})
        mock_response = _make_choice(finish_reason="tool_calls", tool_calls=[tc])

        with patch("opspilot.providers.openai_compat.OpenAI") as mock_cls:
            instance = mock_cls.return_value
            instance.chat.completions.create.return_value = mock_response

            provider = OpenAIProvider(provider_id="openai", api_key="sk-test")
            resp = provider.chat(
                [Message(role="user", content="Search VPN auth")],
                model="gpt-4o",
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
        tc_out = resp.tool_calls[0]
        assert isinstance(tc_out, ToolCall)
        assert tc_out.id == "call_abc123"
        assert tc_out.name == "kb_search"
        assert tc_out.arguments == {"query": "VPN auth"}


# ---------------------------------------------------------------------------
# Test: message format for tool messages
# ---------------------------------------------------------------------------


class TestChatConvertsToolMessages:
    def test_tool_messages_formatted_correctly(self) -> None:
        mock_response = _make_choice(content="done")
        captured_kwargs: dict = {}  # type: ignore[type-arg]

        with patch("opspilot.providers.openai_compat.OpenAI") as mock_cls:
            instance = mock_cls.return_value

            def capture(**kwargs: object) -> MagicMock:
                captured_kwargs.update(kwargs)
                return mock_response

            instance.chat.completions.create.side_effect = capture

            provider = OpenAIProvider(provider_id="openai", api_key="sk-test")
            provider.chat(
                [
                    Message(role="user", content="search please"),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(id="call_01", name="kb_search", arguments={"query": "x"})
                        ],
                    ),
                    Message(
                        role="tool",
                        content='{"hits":[]}',
                        tool_call_id="call_01",
                        name="kb_search",
                    ),
                ],
                model="gpt-4o",
                params=SamplingParams(),
            )

        messages = captured_kwargs["messages"]
        tool_msg = next(m for m in messages if m["role"] == "tool")
        assert tool_msg["tool_call_id"] == "call_01"
        assert tool_msg["content"] == '{"hits":[]}'


# ---------------------------------------------------------------------------
# Test: missing API key raises ProviderError
# ---------------------------------------------------------------------------


class TestMissingApiKeyRaises:
    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
            OpenAIProvider(provider_id="openai", api_key=None)

    def test_openrouter_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
            OpenAIProvider(provider_id="openrouter", api_key=None)

    def test_gemini_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
            OpenAIProvider(provider_id="gemini", api_key=None)

    def test_grok_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GROK_API_KEY", raising=False)

        with pytest.raises(ProviderError, match="GROK_API_KEY"):
            OpenAIProvider(provider_id="grok", api_key=None)


# ---------------------------------------------------------------------------
# Test: base_url resolves per provider_id
# ---------------------------------------------------------------------------


class TestBaseUrlResolution:
    @pytest.mark.parametrize(
        "provider_id, expected_base_url",
        [
            ("openai", "https://api.openai.com/v1"),
            ("openrouter", "https://openrouter.ai/api/v1"),
            ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
            ("grok", "https://api.x.ai/v1"),
        ],
    )
    def test_base_url_resolved_per_provider(
        self, provider_id: str, expected_base_url: str
    ) -> None:
        with patch("opspilot.providers.openai_compat.OpenAI") as mock_cls:
            OpenAIProvider(provider_id=provider_id, api_key="test-key")

        _, kwargs = mock_cls.call_args
        assert kwargs["base_url"] == expected_base_url


# ---------------------------------------------------------------------------
# Test: embed raises ProviderError
# ---------------------------------------------------------------------------


class TestEmbedRaisesNotSupported:
    def test_embed_raises_not_supported(self) -> None:
        with patch("opspilot.providers.openai_compat.OpenAI"):
            provider = OpenAIProvider(provider_id="openai", api_key="sk-test")

        with pytest.raises(ProviderError, match="OllamaProvider"):
            provider.embed(["hello"], model="text-embedding-3-small")


# ---------------------------------------------------------------------------
# Test: health_probe returns True
# ---------------------------------------------------------------------------


class TestHealthProbe:
    def test_health_probe_returns_true(self) -> None:
        with patch("opspilot.providers.openai_compat.OpenAI"):
            provider = OpenAIProvider(provider_id="openai", api_key="sk-test")
            assert provider.health_probe() is True
