"""POST /api/chat/stream — the **Consultation** surface (ADR-0032).

A turn is persisted into a Consultation, and the caller's open **Working set**
supplies the anchors that decide which recorded **Memory** applies (ADR-0031).
The route used to be stateless — the client resent the whole history and nothing
was kept — which is why nothing could be pinned to Memory and why anchored
entries never reached an answer.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, Callable
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...auth import Identity, require_role
from ...providers.types import Message, SamplingParams

# Chat is an operator capability in the role model (ADR-0020): viewers read.
_operator = Depends(require_role("operator"))

router = APIRouter()

_SYSTEM_PROMPT = (
    "You are OpsPilot, an intelligent IT operations assistant. "
    "Answer questions concisely and accurately using the provided knowledge base context when relevant. "
    "If context is insufficient, say so. Respond in the same language as the user."
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model_id: str | None = None
    deep_thinking: bool = False
    consultation_id: str | None = None
    # Explicit anchors win over the caller's Working set — asking about another
    # site is not overruled by what you happen to be working on.
    memory_scope: str | None = None
    memory_asset_id: str | None = None


def _persist(state: Any, consultation_id: str, question: str, answer: str) -> None:
    """Append the turn. Never fatal: losing the transcript must not lose the answer."""
    store = getattr(state, "consultations", None)
    if store is None:
        return
    with contextlib.suppress(Exception):
        if question:
            store.append(consultation_id, role="user", content=question)
        store.append(consultation_id, role="assistant", content=answer)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def route_chat_model(
    *,
    cheap: str | None,
    thinking: str | None,
    deep_thinking: bool,
    explicit: str | None,
    triage: Callable[[], bool],
) -> tuple[str | None, dict[str, Any] | None]:
    """Pick the model for a chat turn and an optional routing step (ADR-0023).

    - ``deep_thinking`` forces the thinking tier (triage is *not* called).
    - else, when both tiers are configured, ``triage()`` decides: complex →
      thinking, simple → cheap, and a ``routing`` step is returned to surface it.
    - else, the cheap tier (or the header-selected model) is used — triage is
      *not* called, so unconfigured tiers leave the header selection untouched.
    """
    if deep_thinking:
        return (thinking or cheap or explicit), None
    if cheap and thinking:
        is_complex = triage()
        tier = thinking if is_complex else cheap
        return tier, {"type": "routing", "tier": "thinking" if is_complex else "cheap"}
    return (cheap or explicit), None


def _triage_is_complex(state: Any, cheap_model_id: str | None, text: str) -> bool:
    """Run the cheap-model complexity triage; any failure degrades to simple."""
    try:
        from ...orchestrator.chat_agent import resolve_model
        from ...orchestrator.triage import triage_complexity

        provider, model = resolve_model(state, cheap_model_id)
        is_complex, _ = triage_complexity(provider, model_name=model.name, text=text)
        return is_complex
    except Exception:  # noqa: BLE001 — triage failure must not break the chat; use cheap
        return False


def answer_chat(state: Any, messages: list[dict[str, str]]) -> str:
    """KB-augmented chat, blocking — the non-SSE core for channel callbacks.

    Mirrors ``chat_stream``'s retrieval + prompt assembly without the SSE
    plumbing; callers run it in an executor (WeCom callback, ADR-0019).
    """
    user_msgs = [m for m in messages if m.get("role") == "user"]
    query = user_msgs[-1]["content"] if user_msgs else ""
    context_chunks: list[str] = []
    if query:
        try:
            from ...kb.retrieval import kb_search

            hits = kb_search(
                query,
                sqlite=state.sqlite,
                lance=state.lance,
                embed_fn=state.embed_fn,
                top_k=4,
            )
            context_chunks = [h.content for h in hits[:4] if h.content]
        except Exception:  # noqa: BLE001 — retrieval is best-effort, chat still answers
            pass
    context_block = ""
    if context_chunks:
        context_block = "\n\n## Relevant KB context\n\n" + "\n\n---\n\n".join(context_chunks)
    provider_msgs: list[Message] = [Message(role="system", content=_SYSTEM_PROMPT + context_block)]
    for m in messages:
        if m.get("role") in ("user", "assistant"):
            provider_msgs.append(
                Message(role=cast('Literal["user", "assistant"]', m["role"]), content=m["content"])
            )
    resp = state.chat_provider.chat(
        provider_msgs,
        model=state.playbook.model.name,
        params=SamplingParams(temperature=0.5, max_tokens=1024),
    )
    return str(resp.content)


def _open_consultation(state: Any, body: ChatRequest, identity: Identity) -> str | None:
    """The Consultation this turn belongs to, starting one if needed.

    Returns ``None`` when no store is mounted, which keeps the route working for
    callers that predate persistence. A Consultation the caller may not see is
    refused rather than silently replaced: writing someone else's conversation is
    worse than failing.
    """
    store = getattr(state, "consultations", None)
    if store is None:
        return None
    if body.consultation_id:
        existing = store.get(body.consultation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="consultation not found")
        if not existing.visible_to(name=identity.name, role=identity.role):
            raise HTTPException(status_code=403, detail="not your consultation")
        return str(existing.id)
    first_user = next((m.content for m in body.messages if m.role == "user"), "")
    return str(store.start(author=identity.name, title=first_user[:80]).id)


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest, request: Request, identity: Identity = _operator
) -> StreamingResponse:
    state = request.app.state
    consultation_id = _open_consultation(state, body, identity)

    # A Working set closed by the inactivity fallback owes its owner one notice,
    # or they misread why the assistant lost the thread (ADR-0032).
    working_sets = getattr(state, "working_sets", None)
    notice = working_sets.take_announcement(identity.name) if working_sets is not None else None
    if working_sets is not None:
        working_sets.touch(identity.name)

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    settings = getattr(state, "settings", None)
    cheap = settings.get("cheap_model_id") if settings is not None else None
    thinking = settings.get("thinking_model_id") if settings is not None else None
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

    def on_step(step: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, step)

    async def _run() -> None:
        try:
            from ...orchestrator.chat_agent import run_chat_agent

            def _plan_and_run() -> Any:
                # Tier routing (deep toggle wins; else cheap-model triage when both
                # tiers are set). The triage LLM call runs here, off the event loop.
                model_id, routing = route_chat_model(
                    cheap=cheap,
                    thinking=thinking,
                    deep_thinking=body.deep_thinking,
                    explicit=body.model_id,
                    triage=lambda: _triage_is_complex(state, cheap, last_user),
                )
                if routing is not None:
                    on_step(routing)
                return run_chat_agent(
                    state,
                    messages,
                    model_id=model_id,
                    on_step=on_step,
                    owner=identity.name,
                    memory_scope=body.memory_scope,
                    memory_asset_id=body.memory_asset_id,
                    consultation_ref=consultation_id,
                )

            result = await loop.run_in_executor(None, _plan_and_run)
            if consultation_id:
                # Persisted after the answer, so a failed turn leaves no
                # half-conversation: the question is only worth keeping with
                # what it produced.
                await loop.run_in_executor(
                    None, _persist, state, consultation_id, last_user, result.content
                )
            await queue.put(
                {
                    "type": "result",
                    "data": {
                        "content": result.content,
                        "citations": result.citations,
                        "usage": result.usage,
                        "consultation_id": consultation_id,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            await queue.put({"type": "error", "message": str(exc)})

    async def event_stream() -> AsyncGenerator[str, None]:
        if notice:
            yield _sse("notice", {"message": notice})
        task = asyncio.create_task(_run())
        while True:
            event = await queue.get()
            etype = event.get("type")
            if etype in ("status", "tool_call", "tool_result", "skill_loaded", "routing"):
                yield _sse(etype, event)
            elif etype == "result":
                yield _sse("result", event["data"])
                break
            elif etype == "error":
                yield _sse("error", {"message": event["message"]})
                break
        await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
