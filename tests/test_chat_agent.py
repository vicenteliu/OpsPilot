"""Chat agent — bounded ReAct loop with kb_search (issue #116)."""

from __future__ import annotations

import types
from typing import Any

import pytest

from opspilot.orchestrator.chat_agent import CHAT_MAX_TURNS, run_chat_agent
from opspilot.providers.types import ChatResponse, ToolCall, Usage
from opspilot.skills import Skill, SkillRegistry


class FakeProvider:
    """Scripts a sequence of ChatResponses; records calls (esp. whether tools passed)."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, model, params, tools=None, timeout_ms=90_000):  # type: ignore[no-untyped-def]
        self.calls.append({"messages": list(messages), "tools": tools, "params": params})
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


class FakeSqlite:
    def get_chunk(self, cid):  # type: ignore[no-untyped-def]
        return {"line_start": 1, "line_end": 5, "heading_path_json": ["VPN"], "anchor": "a"}

    def get_document(self, did):  # type: ignore[no-untyped-def]
        return {"source_path": "kb/vpn.md"}


def _state(
    provider: FakeProvider,
    *,
    kind: str = "anthropic",
    skills: SkillRegistry | None = None,
    web_search_enabled: bool = False,
    mcp_registry: Any = None,
) -> Any:
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
        skills=skills,
        web_search_enabled=web_search_enabled,
        mcp_registry=mcp_registry,
    )


class FakeMcp:
    """Minimal MCP registry: advertises prefixed tools and echoes call results."""

    def __init__(self, tool_names: list[str]) -> None:
        from opspilot.providers.types import ToolDef

        self._defs = [
            ToolDef(name=n, description="", parameters={"type": "object"}) for n in tool_names
        ]
        self.called: list[str] = []

    def refresh_all_tools(self) -> dict[str, Any]:
        return {}

    def as_tool_defs(self) -> list[Any]:
        return list(self._defs)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.called.append(name)
        return types.SimpleNamespace(text=f"result for {name}", is_error=False)


def _registry(*skills: Skill) -> SkillRegistry:
    return SkillRegistry(list(skills))


def _tool_names(call: dict[str, Any]) -> list[str]:
    return [t.name for t in (call["tools"] or [])]


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


# ── web search + MCP tools (issue #120) ──────────────────────────────────────


def test_web_search_offered_and_dispatched(
    canned_hits: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "opspilot.websearch.web_search",
        lambda q, **k: [{"title": "T", "url": "http://x", "snippet": "s"}],
    )
    provider = FakeProvider(
        [
            _resp(
                "",
                finish="tool_call",
                tool_calls=[ToolCall(id="w", name="web_search", arguments={"query": "err"})],
            ),
            _resp("answer with [http://x]"),
        ]
    )
    result = run_chat_agent(
        _state(provider, web_search_enabled=True), [{"role": "user", "content": "err"}]
    )
    assert result.content == "answer with [http://x]"
    assert "web_search" in _tool_names(provider.calls[0])
    # Web results surface as citations (source = url).
    assert any(c["source_path"] == "http://x" for c in result.citations)


def test_web_search_absent_when_disabled(canned_hits: None) -> None:
    provider = FakeProvider([_resp("done")])
    run_chat_agent(_state(provider, web_search_enabled=False), [{"role": "user", "content": "hi"}])
    assert "web_search" not in _tool_names(provider.calls[0])


def test_mcp_tools_offered_and_dispatched(canned_hits: None) -> None:
    mcp = FakeMcp(["srv__lookup"])
    provider = FakeProvider(
        [
            _resp(
                "",
                finish="tool_call",
                tool_calls=[ToolCall(id="m", name="srv__lookup", arguments={"x": 1})],
            ),
            _resp("used mcp"),
        ]
    )
    result = run_chat_agent(_state(provider, mcp_registry=mcp), [{"role": "user", "content": "q"}])
    assert result.content == "used mcp"
    assert "srv__lookup" in _tool_names(provider.calls[0])
    assert mcp.called == ["srv__lookup"]


def test_mcp_absent_when_no_registry(canned_hits: None) -> None:
    provider = FakeProvider([_resp("done")])
    run_chat_agent(_state(provider, mcp_registry=None), [{"role": "user", "content": "hi"}])
    assert _tool_names(provider.calls[0]) == ["kb_search"]


# ── skills (issue #119) ──────────────────────────────────────────────────────


def _skill(sid: str, *, allowed: list[str], trigger: str = "when x") -> Skill:
    return Skill(id=sid, name=sid, trigger=trigger, body="Do the steps.", allowed_tools=allowed)


def test_load_skill_offered_and_no_skills_is_backward_compatible(canned_hits: None) -> None:
    # With skills: load_skill + kb_search are offered.
    reg = _registry(_skill("vpn", allowed=["kb_search"]))
    provider = FakeProvider([_resp("done")])
    run_chat_agent(_state(provider, skills=reg), [{"role": "user", "content": "hi"}])
    assert set(_tool_names(provider.calls[0])) == {"load_skill", "kb_search"}

    # No registry: behaves exactly like #116 (only kb_search).
    provider2 = FakeProvider([_resp("done")])
    run_chat_agent(_state(provider2, skills=None), [{"role": "user", "content": "hi"}])
    assert _tool_names(provider2.calls[0]) == ["kb_search"]


def test_load_skill_injects_body_and_restricts_tools(canned_hits: None) -> None:
    # A skill that allows NO tools → after loading, kb_search is withdrawn.
    reg = _registry(_skill("vpn", allowed=[]))
    provider = FakeProvider(
        [
            _resp(
                "",
                finish="tool_call",
                tool_calls=[ToolCall(id="t", name="load_skill", arguments={"id": "vpn"})],
            ),
            _resp("answered per skill"),
        ]
    )
    steps: list[dict[str, Any]] = []
    result = run_chat_agent(
        _state(provider, skills=reg), [{"role": "user", "content": "vpn"}], on_step=steps.append
    )
    assert result.content == "answered per skill"
    # The skill body was fed back as the tool result.
    tool_msgs = [m for m in provider.calls[1]["messages"] if getattr(m, "role", None) == "tool"]
    assert any("Do the steps." in m.content for m in tool_msgs)
    # After loading a no-tools skill, the next turn offers only load_skill.
    assert _tool_names(provider.calls[1]) == ["load_skill"]
    assert any(s["type"] == "skill_loaded" and s["skill"] == "vpn" for s in steps)


def test_unknown_skill_id_is_reported_not_fatal(canned_hits: None) -> None:
    reg = _registry(_skill("vpn", allowed=["kb_search"]))
    provider = FakeProvider(
        [
            _resp(
                "",
                finish="tool_call",
                tool_calls=[ToolCall(id="t", name="load_skill", arguments={"id": "ghost"})],
            ),
            _resp("recovered"),
        ]
    )
    result = run_chat_agent(_state(provider, skills=reg), [{"role": "user", "content": "q"}])
    assert result.content == "recovered"


def test_thinking_model_uses_prefetch_and_passes_budget(canned_hits: None) -> None:
    provider = FakeProvider([_resp("deep answer")])
    state = _state(provider, kind="anthropic")
    state.playbook.model.params = {
        "temperature": 0.5,
        "max_tokens": 8000,
        "thinking_budget_tokens": 4000,
    }
    result = run_chat_agent(state, [{"role": "user", "content": "hard problem"}])
    assert result.content == "deep answer"
    # Thinking → prefetch path: a single call, no tool loop.
    assert len(provider.calls) == 1
    assert provider.calls[0]["tools"] is None
    # The budget reached the provider via SamplingParams.
    assert provider.calls[0]["params"].thinking_budget_tokens == 4000


def test_weak_model_injects_matched_skill(canned_hits: None) -> None:
    reg = _registry(_skill("vpn", allowed=["kb_search"], trigger="vpn authentication failures"))
    provider = FakeProvider([_resp("answer")])
    steps: list[dict[str, Any]] = []
    run_chat_agent(
        _state(provider, kind="ollama", skills=reg),
        [{"role": "user", "content": "my vpn login keeps failing"}],
        on_step=steps.append,
    )
    # The matched skill body is folded into the (single) system prompt.
    system_msg = provider.calls[0]["messages"][0]
    assert "Do the steps." in system_msg.content
    assert any(s["type"] == "skill_loaded" and s["skill"] == "vpn" for s in steps)
