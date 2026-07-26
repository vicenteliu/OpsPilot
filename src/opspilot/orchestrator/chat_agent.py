"""Chat agent — a bounded ReAct loop for the Chat/assist surface.

Upgrades KB Q&A from a single prefetch-then-answer call into a multi-turn
loop where the model calls ``kb_search`` itself and then answers with
citations (ADR-0022/0023/0024 groundwork). Weak local models (kind
``ollama``) keep the prefetch path — one search injected into the prompt,
no tool loop — mirroring the pipeline's ``retrieval mode`` tool/prefetch
split.

This slice ships only the ``kb_search`` tool; MCP tools and ``load_skill``
land in later slices (#120, #119).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..providers.base import ProviderProtocol
from ..providers.registry import make_provider
from ..providers.types import Message, SamplingParams
from ..session.types import Model
from .tools import make_kb_search_tool, render_tool_result

CHAT_MAX_TURNS = 6  # tool-call rounds before we answer with what we have

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


def _resolve_model(state: Any, model_id: str | None) -> tuple[ProviderProtocol, Model]:
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
    provider, model = _resolve_model(state, model_id)
    tool_def, tool_handler = make_kb_search_tool(
        sqlite=state.sqlite,
        lance=state.lance,
        embed_fn=state.embed_fn,
        default_top_k=getattr(state.playbook.limits, "max_kb_search_results", 5),
    )

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

    def accumulate(resp: Any) -> None:
        usage["input_tokens"] += resp.usage.input_tokens
        usage["output_tokens"] += resp.usage.output_tokens
        usage["cost_usd"] += resp.usage.cost_usd

    sampling = SamplingParams(
        temperature=float(model.params.get("temperature", 0.5)),
        top_p=float(model.params.get("top_p", 0.9)),
        max_tokens=int(model.params.get("max_tokens", 1024)),
    )

    # ── Weak local models: prefetch once, no tool loop. ──────────────────
    if model.kind == "ollama":
        query = _last_user(messages)
        emit({"type": "status", "message": "Searching knowledge base…"})
        payload = tool_handler({"query": query}) if query else {"hits": []}
        collect(payload)
        emit({"type": "tool_result", "tool": "kb_search", "hits": len(payload.get("hits", []))})
        pf_msgs = [
            Message(role="system", content=_SYSTEM_PROMPT_BASE + _render_context(payload))
        ] + _history(messages)
        emit({"type": "status", "message": "Generating response…"})
        pf_resp = provider.chat(pf_msgs, model=model.name, params=sampling)
        accumulate(pf_resp)
        return ChatAgentResult(str(pf_resp.content), list(citations.values()), usage)

    # ── Strong models: ReAct loop with kb_search. ────────────────────────
    provider_msgs: list[Message] = [
        Message(role="system", content=_SYSTEM_PROMPT_BASE + _TOOL_HINT)
    ] + _history(messages)

    resp: Any = None
    for _ in range(CHAT_MAX_TURNS):
        emit({"type": "status", "message": "Thinking…"})
        resp = provider.chat(provider_msgs, model=model.name, params=sampling, tools=[tool_def])
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
