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


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    state = request.app.state
    pb = state.playbook
    chat_provider = state.chat_provider

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def _run() -> None:
        try:
            user_msgs = [m for m in body.messages if m.role == "user"]
            query = user_msgs[-1].content if user_msgs else ""

            await queue.put({"type": "status", "message": "Searching knowledge base…"})

            context_chunks: list[str] = []
            if query:
                try:
                    from ...memory.retrieval import kb_search

                    hits = await loop.run_in_executor(
                        None,
                        lambda: kb_search(
                            query,
                            sqlite=state.sqlite,
                            lance=state.lance,
                            embed_fn=state.embed_fn,
                            top_k=4,
                        ),
                    )
                    context_chunks = [h.content for h in hits[:4] if h.content]
                except Exception:
                    pass

            await queue.put({"type": "status", "message": "Generating response…"})

            context_block = ""
            if context_chunks:
                context_block = "\n\n## Relevant KB context\n\n" + "\n\n---\n\n".join(
                    context_chunks
                )

            provider_msgs: list[Message] = [
                Message(role="system", content=_SYSTEM_PROMPT + context_block)
            ]
            for m in body.messages:
                if m.role in ("user", "assistant"):
                    provider_msgs.append(
                        Message(
                            role=cast('Literal["user", "assistant"]', m.role), content=m.content
                        )
                    )

            resp = await loop.run_in_executor(
                None,
                lambda: chat_provider.chat(
                    provider_msgs,
                    model=pb.model.name,
                    params=SamplingParams(temperature=0.5, max_tokens=1024),
                ),
            )

            await queue.put(
                {
                    "type": "result",
                    "data": {
                        "content": resp.content,
                        "usage": {
                            "input_tokens": resp.usage.input_tokens,
                            "output_tokens": resp.usage.output_tokens,
                            "cost_usd": resp.usage.cost_usd,
                        },
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            await queue.put({"type": "error", "message": str(exc)})

    async def event_stream() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(_run())
        while True:
            event = await queue.get()
            if event["type"] == "status":
                yield _sse("status", {"message": event["message"]})
            elif event["type"] == "result":
                yield _sse("result", event["data"])
                break
            elif event["type"] == "error":
                yield _sse("error", {"message": event["message"]})
                break
        await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
