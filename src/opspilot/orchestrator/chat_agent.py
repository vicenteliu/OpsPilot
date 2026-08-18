"""Chat agent — a bounded ReAct loop for the Chat/assist surface.

Upgrades KB Q&A from a single prefetch-then-answer call into a multi-turn
loop where the model calls ``kb_search`` itself and then answers with
citations (ADR-0022/0023/0024 groundwork). Weak local models (kind
``ollama``) keep the prefetch path — one search injected into the prompt,
no tool loop — mirroring the pipeline's ``retrieval mode`` tool/prefetch
split.

Tools available to the strong-model loop: ``kb_search``, ``load_skill``
(runtime skills, ADR-0022), an opt-in ``web_search`` (self-built, #120), and
any enabled MCP tools (ADR-0024). The prefetch path (weak/thinking models)
stays single-shot with injected KB + skill.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..providers.base import ProviderProtocol
from ..providers.registry import make_provider
from ..providers.types import Message, SamplingParams, ToolDef
from ..session.types import Model
from ..skills import Skill, SkillRegistry
from ..websearch import make_web_search_tool
from .tools import make_kb_search_tool, render_tool_result

CHAT_MAX_TURNS = 6  # tool-call rounds before we answer with what we have


def _opt_float(value: Any) -> float | None:
    """``None`` stays ``None`` — an unset knob must not become a sent one."""
    return None if value is None else float(value)


_LOAD_SKILL_TOOL = ToolDef(
    name="load_skill",
    description=(
        "Load a troubleshooting skill's full procedure by id when the problem matches "
        "its 'use-when' description. Call this before answering a known problem, then "
        "follow the loaded procedure."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": ["id"],
        "properties": {"id": {"type": "string", "description": "The skill id from the catalog."}},
    },
)

_SYSTEM_PROMPT_BASE = (
    "You are OpsPilot, an intelligent IT operations assistant. "
    "Answer questions concisely and accurately using the knowledge base when relevant. "
    "If the knowledge base is insufficient, say so. Respond in the same language as the user."
)
_TOOL_HINT = (
    " You have a kb_search tool — call it to ground your answer in the knowledge base "
    "before answering, and base your answer on what it returns."
)


@dataclass
class ChatAgentResult:
    content: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(
        default_factory=lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )


StepCallback = Callable[[dict[str, Any]], None]


def resolve_model(state: Any, model_id: str | None) -> tuple[ProviderProtocol, Model]:
    """Pick the (provider, model) for this chat, honoring an explicit model_id.

    Mirrors run.py's override resolution: the primary uses the startup-cached
    chat_provider; a selected extra model builds its own provider.
    """
    pb = state.playbook
    primary_id = f"{pb.model.provider_id}/{pb.model.name}"
    if model_id and model_id != primary_id:
        chosen = next(
            (m for m in pb.extra_models if f"{m.provider_id}/{m.name}" == model_id),
            None,
        )
        if chosen is not None:
            provider = make_provider(
                chosen.provider_id,
                kind=chosen.kind,
                api_key=state.cfg.anthropic_api_key if chosen.kind == "anthropic" else None,
                base_url=state.cfg.ollama_base_url if chosen.kind == "ollama" else None,
            )
            return provider, chosen
    return state.chat_provider, pb.model


def _history(messages: list[dict[str, str]]) -> list[Message]:
    return [
        Message(
            role="user" if m.get("role") == "user" else "assistant", content=m.get("content", "")
        )
        for m in messages
        if m.get("role") in ("user", "assistant")
    ]


def _last_user(messages: list[dict[str, str]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def _render_context(payload: dict[str, Any], limit: int = 4) -> str:
    chunks = [h.get("content", "") for h in payload.get("hits", [])[:limit] if h.get("content")]
    if not chunks:
        return ""
    return "\n\n## Relevant KB context\n\n" + "\n\n---\n\n".join(chunks)


def _catalog_prompt(registry: SkillRegistry) -> str:
    """A compact skill catalog for the system prompt (progressive disclosure)."""
    lines = [f"- {e['id']}: {e['trigger'] or e['name']}" for e in registry.catalog()]
    if not lines:
        return ""
    return (
        "\n\nAvailable skills — when a problem matches one, call load_skill(id) to load its "
        "full procedure, then follow it:\n" + "\n".join(lines)
    )


def _skill_body(skill: Skill) -> str:
    return f"# Skill: {skill.name}\n\n{skill.body}"


def run_chat_agent(
    state: Any,
    messages: list[dict[str, str]],
    *,
    model_id: str | None = None,
    on_step: StepCallback | None = None,
) -> ChatAgentResult:
    """Run the chat as a bounded ReAct loop; return the answer + KB citations.

    ``on_step`` (optional) receives progress dicts — ``status`` /
    ``tool_call`` / ``tool_result`` — for streaming; the return value carries
    the final answer, deduped citations, and accumulated token usage.
    """
    provider, model = resolve_model(state, model_id)
    tool_def, tool_handler = make_kb_search_tool(
        sqlite=state.sqlite,
        lance=state.lance,
        embed_fn=state.embed_fn,
        default_top_k=getattr(state.playbook.limits, "max_kb_search_results", 5),
    )
    registry: SkillRegistry | None = getattr(state, "skills", None)

    citations: dict[str, dict[str, Any]] = {}
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    def emit(step: dict[str, Any]) -> None:
        if on_step is not None:
            on_step(step)

    def collect(payload: dict[str, Any]) -> None:
        for h in payload.get("hits", []):
            cid = h.get("chunk_id")
            if cid and cid not in citations:
                c = h.get("citation") or {}
                citations[cid] = {
                    "chunk_id": cid,
                    "document_id": h.get("document_id"),
                    "source_path": c.get("source_path"),
                    "heading_path": c.get("heading_path") or [],
                    "snippet": (h.get("content") or "")[:240],
                }

    def collect_web(payload: dict[str, Any]) -> None:
        for r in payload.get("results", []):
            url = r.get("url") or r.get("title")
            if url and url not in citations:
                citations[url] = {
                    "chunk_id": url,
                    "document_id": None,
                    "source_path": r.get("url") or "",
                    "heading_path": [],
                    "snippet": (r.get("snippet") or "")[:240],
                }

    def accumulate(resp: Any) -> None:
        usage["input_tokens"] += resp.usage.input_tokens
        usage["output_tokens"] += resp.usage.output_tokens
        usage["cost_usd"] += resp.usage.cost_usd

    thinking_budget = int(model.params.get("thinking_budget_tokens") or 0)
    sampling = SamplingParams(
        temperature=_opt_float(model.params.get("temperature")),
        top_p=_opt_float(model.params.get("top_p")),
        max_tokens=int(model.params.get("max_tokens", 1024)),
        thinking_budget_tokens=thinking_budget or None,
    )

    # ── Prefetch path: weak local models, and thinking models. ───────────
    # Extended thinking + multi-turn tool use needs thinking-block echo we don't
    # model, so a thinking turn does one deeply-reasoned call over injected KB +
    # skill instead of the tool loop.
    if model.kind == "ollama" or thinking_budget > 0:
        query = _last_user(messages)
        # Weak models can't drive load_skill — inject the best-matching skill.
        matched = registry.match(query) if registry is not None else None
        skill_block = ""
        if matched is not None:
            emit({"type": "skill_loaded", "skill": matched.id})
            skill_block = "\n\n" + _skill_body(matched)
        emit({"type": "status", "message": "Searching knowledge base…"})
        payload = tool_handler({"query": query}) if query else {"hits": []}
        collect(payload)
        emit({"type": "tool_result", "tool": "kb_search", "hits": len(payload.get("hits", []))})
        pf_msgs = [
            Message(
                role="system",
                content=_SYSTEM_PROMPT_BASE + skill_block + _render_context(payload),
            )
        ] + _history(messages)
        emit({"type": "status", "message": "Generating response…"})
        pf_resp = provider.chat(pf_msgs, model=model.name, params=sampling)
        accumulate(pf_resp)
        return ChatAgentResult(str(pf_resp.content), list(citations.values()), usage)

    # ── Strong models: ReAct loop with kb_search (+ load_skill, web, MCP). ──
    has_skills = registry is not None and len(registry) > 0

    # Optional web_search tool (opt-in; egresses the query — ADR-0024/#120).
    web_tool: ToolDef | None = None
    web_handler = None
    if getattr(state, "web_search_enabled", False):
        web_tool, web_handler = make_web_search_tool()

    # MCP tools from the registry, injected into the chat loop (ADR-0024).
    mcp_registry = getattr(state, "mcp_registry", None)
    mcp_tool_defs: list[ToolDef] = []
    if mcp_registry is not None:
        try:
            mcp_registry.refresh_all_tools()
            mcp_tool_defs = mcp_registry.as_tool_defs()
        except Exception:  # noqa: BLE001 — a bad MCP server must not break chat
            mcp_tool_defs = []
    mcp_names = {t.name for t in mcp_tool_defs}

    domain_tools: list[ToolDef] = [tool_def]
    if web_tool is not None:
        domain_tools.append(web_tool)
    domain_tools += mcp_tool_defs

    system_prompt = _SYSTEM_PROMPT_BASE + _TOOL_HINT
    if has_skills and registry is not None:
        system_prompt += _catalog_prompt(registry)
    provider_msgs: list[Message] = [Message(role="system", content=system_prompt)] + _history(
        messages
    )

    active_skill: Skill | None = None  # once loaded, restricts the domain tools

    def _tools_for_turn() -> list[ToolDef]:
        tools: list[ToolDef] = [_LOAD_SKILL_TOOL] if has_skills else []
        # Before a skill is loaded, all domain tools are available; after,
        # only those the skill declares (ADR-0022).
        if active_skill is None:
            tools += domain_tools
        else:
            allowed = set(active_skill.allowed_tools)
            tools += [t for t in domain_tools if t.name in allowed]
        return tools

    resp: Any = None
    for _ in range(CHAT_MAX_TURNS):
        emit({"type": "status", "message": "Thinking…"})
        resp = provider.chat(
            provider_msgs, model=model.name, params=sampling, tools=_tools_for_turn()
        )
        accumulate(resp)

        if resp.finish_reason == "tool_call" and resp.tool_calls:
            provider_msgs.append(
                Message(
                    role="assistant", content=resp.content or "", tool_calls=list(resp.tool_calls)
                )
            )
            for tc in resp.tool_calls:
                if tc.name == "kb_search":
                    emit(
                        {
                            "type": "tool_call",
                            "tool": "kb_search",
                            "query": str(tc.arguments.get("query", "")),
                        }
                    )
                    try:
                        payload = tool_handler(tc.arguments)
                    except Exception as e:  # noqa: BLE001 — surface tool errors to the model
                        payload = {"hits": [], "_error": f"{type(e).__name__}: {e}"}
                    collect(payload)
                    emit(
                        {
                            "type": "tool_result",
                            "tool": "kb_search",
                            "hits": len(payload.get("hits", [])),
                        }
                    )
                    rendered = render_tool_result(payload)
                elif tc.name == "load_skill" and registry is not None:
                    sid = str(tc.arguments.get("id", ""))
                    skill = registry.get(sid)
                    if skill is None:
                        rendered = render_tool_result({"_error": f"unknown skill: {sid}"})
                    else:
                        active_skill = skill
                        emit({"type": "skill_loaded", "skill": skill.id})
                        rendered = _skill_body(skill)
                elif tc.name == "web_search" and web_handler is not None:
                    emit(
                        {
                            "type": "tool_call",
                            "tool": "web_search",
                            "query": str(tc.arguments.get("query", "")),
                        }
                    )
                    try:
                        payload = web_handler(tc.arguments)
                    except Exception as e:  # noqa: BLE001 — surface tool errors to the model
                        payload = {"results": [], "_error": f"{type(e).__name__}: {e}"}
                    collect_web(payload)
                    emit(
                        {
                            "type": "tool_result",
                            "tool": "web_search",
                            "hits": len(payload.get("results", [])),
                        }
                    )
                    rendered = render_tool_result(payload)
                elif tc.name in mcp_names and mcp_registry is not None:
                    emit({"type": "tool_call", "tool": tc.name, "query": ""})
                    try:
                        mcp_result = mcp_registry.call_tool(tc.name, tc.arguments)
                        payload = {"text": mcp_result.text, "is_error": mcp_result.is_error}
                    except Exception as e:  # noqa: BLE001 — surface tool errors to the model
                        payload = {"_error": f"{type(e).__name__}: {e}"}
                    emit({"type": "tool_result", "tool": tc.name, "hits": 0})
                    rendered = render_tool_result(payload)
                else:
                    rendered = render_tool_result({"_error": f"unknown tool: {tc.name}"})
                provider_msgs.append(
                    Message(role="tool", content=rendered, tool_call_id=tc.id, name=tc.name)
                )
            continue

        return ChatAgentResult(str(resp.content), list(citations.values()), usage)

    # Max turns exhausted — answer with whatever the last turn produced.
    fallback = (resp.content if resp is not None else "") or (
        "I couldn't finish searching in time — please narrow your question."
    )
    return ChatAgentResult(str(fallback), list(citations.values()), usage)
