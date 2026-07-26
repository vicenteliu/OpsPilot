"""POST /api/chat/stream — KB-augmented conversational chat."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any, Literal, cast

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...providers.types import Message, SamplingParams

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


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def resolve_tier_model_id(
    *, cheap: str | None, thinking: str | None, deep_thinking: bool, explicit: str | None
) -> str | None:
    """Pick the model for a chat turn from the configured tiers (ADR-0023).

    Deep-thinking prefers the thinking tier; a normal turn prefers the cheap
    tier. Either degrades to the other tier, then to the explicitly-selected
    model, so unconfigured tiers leave the header selection untouched. Auto
    complexity triage (#118) layers on top of this later.
    """
    if deep_thinking:
        return thinking or cheap or explicit
    return cheap or explicit


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
            from ...memory.retrieval import kb_search

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


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    state = request.app.state

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    # Resolve the tier: deep-thinking → thinking tier, else cheap tier; falls
    # back to the header-selected model when tiers aren't configured (ADR-0023).
    settings = getattr(state, "settings", None)
    model_id = resolve_tier_model_id(
        cheap=settings.get("cheap_model_id") if settings is not None else None,
        thinking=settings.get("thinking_model_id") if settings is not None else None,
        deep_thinking=body.deep_thinking,
        explicit=body.model_id,
    )

    def on_step(step: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, step)

    async def _run() -> None:
        try:
            from ...orchestrator.chat_agent import run_chat_agent

            result = await loop.run_in_executor(
                None,
                lambda: run_chat_agent(state, messages, model_id=model_id, on_step=on_step),
            )
            await queue.put(
                {
                    "type": "result",
                    "data": {
                        "content": result.content,
                        "citations": result.citations,
                        "usage": result.usage,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            await queue.put({"type": "error", "message": str(exc)})

    async def event_stream() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(_run())
        while True:
            event = await queue.get()
            etype = event.get("type")
            if etype in ("status", "tool_call", "tool_result", "skill_loaded"):
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
