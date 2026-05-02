"""Tests for ``opspilot.providers.ollama``.

Two layers:

* **Unit (mocked transport)** — ``httpx.MockTransport`` simulates Ollama's
  HTTP responses; runs everywhere, no Ollama install required.
* **Integration (``@pytest.mark.requires_ollama``)** — hits a real local
  Ollama. Excluded by default (``make test``); enabled by ``make
  test-ollama`` after ``make ollama-up && make ollama-pull``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from opspilot.errors import ConfigError, ProviderError
from opspilot.providers import (
    ChatResponse,
    Message,
    OllamaProvider,
    SamplingParams,
    ToolCall,
    ToolDef,
    Usage,
    make_provider,
)
from opspilot.providers.base import ProviderProtocol
from opspilot.providers.ollama import _normalize_finish_reason

# ──────────────────────────────────────────────────────────────────────────
#  Type-level checks
# ──────────────────────────────────────────────────────────────────────────


class TestProtocol:
    def test_ollama_satisfies_protocol(self) -> None:
        p = OllamaProvider()
        try:
            assert isinstance(p, ProviderProtocol)  # runtime_checkable
        finally:
            p.close()


# ──────────────────────────────────────────────────────────────────────────
#  Helpers under test
# ──────────────────────────────────────────────────────────────────────────


class TestFinishReasonNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("stop", "stop"),
            ("length", "length"),
            ("tool_calls", "tool_call"),
            ("tool_call", "tool_call"),
            ("function_call", "tool_call"),
            ("content_filter", "content_filter"),
            (None, "stop"),
            ("weird-future-value", "stop"),
        ],
    )
    def test_mapping(self, raw: str | None, expected: str) -> None:
        assert _normalize_finish_reason(raw) == expected


# ──────────────────────────────────────────────────────────────────────────
#  Unit tests via httpx.MockTransport
# ──────────────────────────────────────────────────────────────────────────


def _make_provider_with_handler(handler) -> OllamaProvider:
    """Build an OllamaProvider whose HTTP client uses our mock handler."""
    client = httpx.Client(
        base_url="http://localhost:11434",
        transport=httpx.MockTransport(handler),
    )
    return OllamaProvider(client=client)


class TestHealthProbe:
    def test_ok(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/tags"
            return httpx.Response(200, json={"models": []})

        p = _make_provider_with_handler(handler)
        assert p.health_probe() is True

    def test_connection_refused(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused", request=request)

        p = _make_provider_with_handler(handler)
        assert p.health_probe() is False

    def test_500(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        p = _make_provider_with_handler(handler)
        # health_probe returns True iff status is 200.
        assert p.health_probe() is False


class TestChat:
    def test_simple(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/chat/completions"
            body = json.loads(request.content)
            assert body["model"] == "qwen2.5:14b-instruct"
            assert body["stream"] is False
            assert body["messages"][0]["content"] == "hello"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "hi there"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                },
            )

        p = _make_provider_with_handler(handler)
        resp = p.chat(
            [Message(role="user", content="hello")],
            model="qwen2.5:14b-instruct",
            params=SamplingParams(),
        )
        assert isinstance(resp, ChatResponse)
        assert resp.content == "hi there"
        assert resp.finish_reason == "stop"
        assert resp.usage.input_tokens == 5
        assert resp.usage.output_tokens == 3
        assert resp.usage.cost_usd == 0.0  # local; always free
        assert resp.tool_calls is None

    def test_tool_call(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            # Tool definitions should be sent through.
            assert body.get("tools")
            assert body["tools"][0]["function"]["name"] == "kb_search"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_001",
                                        "type": "function",
                                        "function": {
                                            "name": "kb_search",
                                            "arguments": '{"query":"VPN auth"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4},
                },
            )

        p = _make_provider_with_handler(handler)
        resp = p.chat(
            [Message(role="user", content="search for VPN auth")],
            model="qwen2.5:14b-instruct",
            params=SamplingParams(),
            tools=[
                ToolDef(
                    name="kb_search",
                    description="Search the KB",
                    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
                )
            ],
        )
        assert resp.finish_reason == "tool_call"
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        tc = resp.tool_calls[0]
        assert tc.id == "call_001"
        assert tc.name == "kb_search"
        assert tc.arguments == {"query": "VPN auth"}

    def test_seed_passed_through(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "x"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )

        p = _make_provider_with_handler(handler)
        p.chat(
            [Message(role="user", content="x")],
            model="m",
            params=SamplingParams(seed=42, stop=["END"]),
        )
        assert captured["seed"] == 42
        assert captured["stop"] == ["END"]

    def test_serialize_assistant_with_tool_calls(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )

        p = _make_provider_with_handler(handler)
        p.chat(
            [
                Message(role="user", content="q"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="x", name="f", arguments={"a": 1})],
                ),
                Message(role="tool", content='{"ok":true}', tool_call_id="x"),
            ],
            model="m",
            params=SamplingParams(),
        )
        assistant_msg = captured["messages"][1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "f"
        # arguments are JSON-serialised string in the wire format
        assert assistant_msg["tool_calls"][0]["function"]["arguments"] == '{"a": 1}'
        tool_msg = captured["messages"][2]
        assert tool_msg["tool_call_id"] == "x"

    def test_http_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal error")

        p = _make_provider_with_handler(handler)
        with pytest.raises(ProviderError) as excinfo:
            p.chat(
                [Message(role="user", content="x")],
                model="m",
                params=SamplingParams(),
            )
        assert "http_500" in str(excinfo.value.error_code)

    def test_network_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("conn refused", request=request)

        p = _make_provider_with_handler(handler)
        with pytest.raises(ProviderError) as excinfo:
            p.chat(
                [Message(role="user", content="x")],
                model="m",
                params=SamplingParams(),
            )
        assert excinfo.value.error_code == "network_error"

    def test_malformed_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        p = _make_provider_with_handler(handler)
        with pytest.raises(ProviderError, match="malformed response"):
            p.chat(
                [Message(role="user", content="x")],
                model="m",
                params=SamplingParams(),
            )


class TestEmbed:
    def test_single(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/embeddings"
            body = json.loads(request.content)
            assert body == {"model": "nomic-embed-text", "prompt": "hello"}
            return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

        p = _make_provider_with_handler(handler)
        out = p.embed(["hello"], model="nomic-embed-text")
        assert out == [[0.1, 0.2, 0.3]]

    def test_batch_via_loop(self) -> None:
        seen_prompts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen_prompts.append(body["prompt"])
            return httpx.Response(200, json={"embedding": [float(len(body["prompt"]))]})

        p = _make_provider_with_handler(handler)
        out = p.embed(["a", "bb", "ccc"], model="m")
        assert seen_prompts == ["a", "bb", "ccc"]
        assert out == [[1.0], [2.0], [3.0]]

    def test_malformed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"oops": []})

        p = _make_provider_with_handler(handler)
        with pytest.raises(ProviderError, match="no 'embedding' field"):
            p.embed(["x"], model="m")


# ──────────────────────────────────────────────────────────────────────────
#  Factory
# ──────────────────────────────────────────────────────────────────────────


class TestFactory:
    def test_default_returns_ollama(self) -> None:
        p = make_provider()
        try:
            assert isinstance(p, OllamaProvider)
            assert p.provider_id == "ollama-local"
            assert p.kind == "ollama"
        finally:
            if isinstance(p, OllamaProvider):
                p.close()

    def test_alias(self) -> None:
        p = make_provider("ollama")
        try:
            assert isinstance(p, OllamaProvider)
        finally:
            if isinstance(p, OllamaProvider):
                p.close()

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ConfigError, match="not supported in Stage 1"):
            make_provider("anthropic-claude")

    def test_base_url_override(self) -> None:
        p = make_provider(base_url="http://other:11434")
        try:
            assert p.base_url == "http://other:11434"
        finally:
            if isinstance(p, OllamaProvider):
                p.close()


# ──────────────────────────────────────────────────────────────────────────
#  Integration tests (require a running Ollama)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.requires_ollama
class TestIntegration:
    """Real Ollama. Requires::

    make ollama-up
    make ollama-pull
    make test-ollama
    """

    @pytest.fixture(scope="class")
    def provider(self) -> OllamaProvider:
        p = OllamaProvider()
        if not p.health_probe():
            p.close()
            pytest.skip("Ollama not reachable at http://localhost:11434")
        yield p
        p.close()

    def test_health(self, provider: OllamaProvider) -> None:
        assert provider.health_probe() is True

    def test_chat_smoke(self, provider: OllamaProvider) -> None:
        resp = provider.chat(
            [Message(role="user", content="reply with literally just the word: pong")],
            model="gemma4:e4b",
            params=SamplingParams(temperature=0, max_tokens=8),
        )
        assert isinstance(resp, ChatResponse)
        assert isinstance(resp.usage, Usage)
        assert resp.content  # non-empty

    def test_embed_smoke(self, provider: OllamaProvider) -> None:
        out = provider.embed(["hello world"], model="nomic-embed-text-v2-moe")
        assert len(out) == 1
        # nomic-embed-text-v2-moe defaults to 768-dim (Matryoshka; truncatable).
        assert len(out[0]) == 768
        assert all(isinstance(x, float) for x in out[0])
