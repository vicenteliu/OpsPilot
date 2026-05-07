"""POST /api/run and POST /api/run/stream routes."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ...orchestrator.ticket_summary import run_ticket_summary
from ...orchestrator.types import RunRequest as OrchestratorRunRequest
from ...providers.registry import make_provider
from ..types import ApiRunRequest, ApiRunResponse, ApiTokenUsage

router = APIRouter()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _resolve_provider_and_playbook(body: ApiRunRequest, state: Any) -> tuple[Any, Any]:
    """Return (chat_provider, effective_playbook) for a run request."""
    pb = state.playbook
    primary_id = f"{pb.model.provider_id}/{pb.model.name}"
    override_model = (
        next(
            (m for m in pb.extra_models if f"{m.provider_id}/{m.name}" == body.model_id),
            None,
        )
        if body.model_id and body.model_id != primary_id
        else None
    )
    if override_model is not None:
        cfg = state.cfg
        override_provider = make_provider(
            override_model.provider_id,
            kind=override_model.kind,
            api_key=cfg.anthropic_api_key if override_model.kind == "anthropic" else None,
            base_url=cfg.ollama_base_url if override_model.kind == "ollama" else None,
        )
        override_retrieval_mode = (
            "prefetch" if override_model.kind == "ollama" else pb.retrieval.mode
        )
        effective_playbook = dataclasses.replace(
            pb,
            model=override_model,
            extra_models=[],
            retrieval=dataclasses.replace(pb.retrieval, mode=override_retrieval_mode),
        )
        return override_provider, effective_playbook
    return state.chat_provider, pb


@router.post("/run", response_model=ApiRunResponse)
async def run_ticket(body: ApiRunRequest, request: Request) -> ApiRunResponse:
    """Accept a ticket JSON and run the ticket summary playbook (blocking)."""
    state = request.app.state
    chat_provider, effective_playbook = _resolve_provider_and_playbook(body, state)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(body.input, f, ensure_ascii=False)
        ticket_path = Path(f.name)

    try:
        loop = asyncio.get_event_loop()
        orch_request = OrchestratorRunRequest(
            playbook=effective_playbook,
            input_path=ticket_path,
            owner="api:default",
        )

        def _run() -> Any:
            return run_ticket_summary(
                orch_request,
                session_manager=state.session_mgr,
                provider=chat_provider,
                redactor=state.redactor,
                embed_fn=state.embed_fn,
                sqlite_store=state.sqlite,
                lance_store=state.lance,
                mcp_registry=getattr(state, "mcp_registry", None),
            )

        result = await loop.run_in_executor(None, _run)
    finally:
        ticket_path.unlink(missing_ok=True)

    return ApiRunResponse(
        session_id=result.session_id,
        artifact_id=result.artifact_id,
        schema_valid=result.schema_valid,
        result=result.summary,
        error=result.error,
        usage=ApiTokenUsage(
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=result.usage.cost_usd,
        ),
    )


@router.post("/run/stream")
async def run_ticket_stream(body: ApiRunRequest, request: Request) -> StreamingResponse:
    """Run the ticket playbook, streaming SSE progress events then the final result.

    Event types emitted:
      status  — {"message": str}           progress update
      result  — full ApiRunResponse payload
      error   — {"message": str}           on unhandled exception
    """
    state = request.app.state
    chat_provider, effective_playbook = _resolve_provider_and_playbook(body, state)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(body.input, f, ensure_ascii=False)
        ticket_path = Path(f.name)

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def on_progress(msg: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "status", "message": msg})

    orch_request = OrchestratorRunRequest(
        playbook=effective_playbook,
        input_path=ticket_path,
        owner="api:default",
    )

    async def _run_in_thread() -> None:
        try:
            result = await loop.run_in_executor(
                None,
                lambda: run_ticket_summary(
                    orch_request,
                    session_manager=state.session_mgr,
                    provider=chat_provider,
                    redactor=state.redactor,
                    embed_fn=state.embed_fn,
                    sqlite_store=state.sqlite,
                    lance_store=state.lance,
                    mcp_registry=getattr(state, "mcp_registry", None),
                    on_progress=on_progress,
                ),
            )
            payload: dict[str, Any] = {
                "session_id": result.session_id,
                "artifact_id": result.artifact_id,
                "schema_valid": result.schema_valid,
                "result": result.summary,
                "error": result.error,
                "usage": {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "cost_usd": result.usage.cost_usd,
                } if result.usage else None,
            }
            await queue.put({"type": "result", "data": payload})
        except Exception as exc:  # noqa: BLE001
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            ticket_path.unlink(missing_ok=True)

    async def event_stream() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(_run_in_thread())
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
