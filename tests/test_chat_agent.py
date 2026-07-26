"""Chat agent — bounded ReAct loop with kb_search (issue #116)."""

from __future__ import annotations

import types
from typing import Any

import pytest

from opspilot.orchestrator.chat_agent import CHAT_MAX_TURNS, run_chat_agent
from opspilot.providers.types import ChatResponse, ToolCall, Usage


class FakeProvider:
    """Scripts a sequence of ChatResponses; records calls (esp. whether tools passed)."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, model, params, tools=None, timeout_ms=90_000):  # type: ignore[no-untyped-def]
        self.calls.append({"messages": list(messages), "tools": tools})
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


class FakeSqlite:
    def get_chunk(self, cid):  # type: ignore[no-untyped-def]
        return {"line_start": 1, "line_end": 5, "heading_path_json": ["VPN"], "anchor": "a"}

    def get_document(self, did):  # type: ignore[no-untyped-def]
        return {"source_path": "kb/vpn.md"}


def _state(provider: FakeProvider, *, kind: str = "anthropic") -> Any:
    model = types.SimpleNamespace(
        provider_id="anthropic" if kind == "anthropic" else "ollama-local",
        kind=kind,
        name="m1",
        params={"temperature": 0.5, "max_tokens": 512},
    )
    playbook = types.SimpleNamespace(
        model=model, extra_models=[], limits=types.SimpleNamespace(max_kb_search_results=5)
    )
    return types.SimpleNamespace(
        playbook=playbook,
        sqlite=FakeSqlite(),
        lance=object(),
        embed_fn=lambda q: [0.0],
        cfg=types.SimpleNamespace(anthropic_api_key="k", ollama_base_url="http://x"),
        chat_provider=provider,
    )


@pytest.fixture
def canned_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make kb_search (used inside make_kb_search_tool) return one fixed hit."""
    from opspilot.memory.retrieval import Hit

    def fake_kb_search(query, **kwargs):  # type: ignore[no-untyped-def]
        return [
            Hit(
                chunk_id="chk_abc",
                score=0.9,
                rank_vector=1,
                rank_fts=1,
                document_id="doc_vpn",
                namespace="ns",
                content="Reset the VPN gateway to clear stale sessions.",
            )
        ]

    monkeypatch.setattr("opspilot.orchestrator.tools.kb_search", fake_kb_search)


def _resp(content: str, *, finish: str = "stop", tool_calls=None) -> ChatResponse:
    return ChatResponse(
        content=content,
        finish_reason=finish,  # type: ignore[arg-type]
        tool_calls=tool_calls,
        usage=Usage(input_tokens=10, output_tokens=5, cost_usd=0.001),
    )


def test_react_loop_calls_kb_search_then_answers(canned_hits: None) -> None:
    provider = FakeProvider(
        [
            _resp(
                "",
                finish="tool_call",
                tool_calls=[ToolCall(id="t1", name="kb_search", arguments={"query": "vpn"})],
            ),
            _resp("Reset the gateway. [chk_abc]"),
        ]
    )
    steps: list[dict[str, Any]] = []
    result = run_chat_agent(
        _state(provider), [{"role": "user", "content": "vpn broken"}], on_step=steps.append
    )
    assert result.content == "Reset the gateway. [chk_abc]"
    # kb_search executed → one citation collected from the fixed hit.
    assert [c["chunk_id"] for c in result.citations] == ["chk_abc"]
    assert result.citations[0]["source_path"] == "kb/vpn.md"
    # tool_call / tool_result steps emitted.
    assert any(s["type"] == "tool_call" and s["tool"] == "kb_search" for s in steps)
    assert any(s["type"] == "tool_result" and s["hits"] == 1 for s in steps)
    # usage accumulated across both rounds.
    assert result.usage["input_tokens"] == 20


def test_tools_offered_to_strong_model(canned_hits: None) -> None:
    provider = FakeProvider([_resp("done")])
    run_chat_agent(_state(provider, kind="anthropic"), [{"role": "user", "content": "hi"}])
    assert provider.calls[0]["tools"] is not None  # strong model gets the kb_search tool


def test_weak_model_uses_prefetch_no_tools(canned_hits: None) -> None:
    provider = FakeProvider([_resp("answer from context")])
    result = run_chat_agent(_state(provider, kind="ollama"), [{"role": "user", "content": "vpn"}])
    assert result.content == "answer from context"
    # Prefetch path: a single call, no tools passed, but citations still collected.
    assert len(provider.calls) == 1
    assert provider.calls[0]["tools"] is None
    assert [c["chunk_id"] for c in result.citations] == ["chk_abc"]


def test_max_turns_cap_enforced(canned_hits: None) -> None:
    # Always returns a tool_call → the loop must stop at the cap, not spin forever.
    provider = FakeProvider(
        [
            _resp(
                "",
                finish="tool_call",
                tool_calls=[ToolCall(id="t", name="kb_search", arguments={"query": "q"})],
            )
        ]
    )
    result = run_chat_agent(_state(provider), [{"role": "user", "content": "q"}])
    assert len(provider.calls) == CHAT_MAX_TURNS
    assert result.content  # best-effort fallback text, not a crash


def test_unknown_tool_is_reported_not_fatal(canned_hits: None) -> None:
    provider = FakeProvider(
        [
            _resp(
                "",
                finish="tool_call",
                tool_calls=[ToolCall(id="t", name="mystery", arguments={})],
            ),
            _resp("recovered"),
        ]
    )
    result = run_chat_agent(_state(provider), [{"role": "user", "content": "q"}])
    assert result.content == "recovered"  # loop fed back an error and continued
