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

from ...orchestrator.classify import classify_work_item, declared_type
from ...orchestrator.ticket_summary import run_ticket_summary
from ...orchestrator.types import RunRequest as OrchestratorRunRequest
from ...providers.registry import make_provider
from ..types import ApiRunRequest, ApiRunResponse, ApiTokenUsage

router = APIRouter()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _select_playbook_for_type(work_item_type: str, state: Any) -> Any:
    """Map a Work item type to its loaded playbook (incident is the default)."""
    if work_item_type == "service_request":
        return getattr(state, "request_fulfillment_pb", None) or state.playbook
    return state.playbook


def _apply_model_override(body: ApiRunRequest, state: Any, pb: Any) -> tuple[Any, Any]:
    """Apply a ``model_id`` override (if any) to an already-chosen base playbook."""
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


def _resolve_provider_and_playbook(body: ApiRunRequest, state: Any) -> tuple[Any, Any]:
    """Return (chat_provider, effective_playbook) for an explicit playbook_id.

    Base playbook selected by ``playbook_id`` (incident default vs the
    service-request playbook); model overrides then apply.
    """
    pb = state.playbook
    request_pb = getattr(state, "request_fulfillment_pb", None)
    if body.playbook_id and request_pb is not None and body.playbook_id == request_pb.id:
        pb = request_pb
    return _apply_model_override(body, state, pb)


def _resolve_run_plan(
    body: ApiRunRequest, state: Any, ticket_path: Path
) -> tuple[Any, Any, dict[str, Any] | None, bool]:
    """Decide which playbook to run (declared-first).

    Precedence: explicit ``playbook_id`` > input-declared ``work_item_type`` >
    LLM classification. Below the confidence threshold the run is withheld for a
    human pick. Returns (provider, playbook, classification, needs_confirmation).
    When needs_confirmation is True, provider/playbook are None.

    Blocking (classification does a provider call) — call inside an executor.
    """
    if body.playbook_id:
        provider, pb = _resolve_provider_and_playbook(body, state)
        return provider, pb, None, False

    declared = declared_type(body.input)
    if declared is not None:
        provider, pb = _apply_model_override(body, state, _select_playbook_for_type(declared, state))
        return provider, pb, None, False

    result = classify_work_item(
        ticket_path,
        playbook=state.classify_pb,
        provider=state.chat_provider,
        redactor=state.redactor,
    )
    classification = result.as_dict()
    if result.confidence < state.classify_threshold:
        return None, None, classification, True
    provider, pb = _apply_model_override(
        body, state, _select_playbook_for_type(result.work_item_type, state)
    )
    return provider, pb, classification, False


@router.post("/run", response_model=ApiRunResponse)
async def run_ticket(body: ApiRunRequest, request: Request) -> ApiRunResponse:
    """Accept a work item JSON, classify if needed, and run the matching playbook."""
    state = request.app.state

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(body.input, f, ensure_ascii=False)
        ticket_path = Path(f.name)

    try:
        loop = asyncio.get_event_loop()

        def _plan_and_run() -> tuple[Any, dict[str, Any] | None, bool]:
            provider, pb, classification, needs_conf = _resolve_run_plan(body, state, ticket_path)
            if needs_conf:
                return None, classification, True
            orch_request = OrchestratorRunRequest(
                playbook=pb, input_path=ticket_path, owner="api:default"
            )
            res = run_ticket_summary(
                orch_request,
                session_manager=state.session_mgr,
                provider=provider,
                redactor=state.redactor,
                embed_fn=state.embed_fn,
                sqlite_store=state.sqlite,
                lance_store=state.lance,
                mcp_registry=getattr(state, "mcp_registry", None),
            )
            return res, classification, False

        result, classification, needs_conf = await loop.run_in_executor(None, _plan_and_run)
    finally:
        ticket_path.unlink(missing_ok=True)

    if needs_conf:
        return ApiRunResponse(
            session_id="",
            artifact_id=None,
            schema_valid=False,
            result={},
            error=None,
            usage=None,
            classification=classification,
            needs_confirmation=True,
        )

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
        classification=classification,
        needs_confirmation=False,
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

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(body.input, f, ensure_ascii=False)
        ticket_path = Path(f.name)

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def on_progress(msg: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "status", "message": msg})

    def _plan_and_run() -> tuple[Any, dict[str, Any] | None, bool]:
        provider, pb, classification, needs_conf = _resolve_run_plan(body, state, ticket_path)
        if needs_conf:
            return None, classification, True
        orch_request = OrchestratorRunRequest(
            playbook=pb, input_path=ticket_path, owner="api:default"
        )
        res = run_ticket_summary(
            orch_request,
            session_manager=state.session_mgr,
            provider=provider,
            redactor=state.redactor,
            embed_fn=state.embed_fn,
            sqlite_store=state.sqlite,
            lance_store=state.lance,
            mcp_registry=getattr(state, "mcp_registry", None),
            on_progress=on_progress,
        )
        return res, classification, False

    async def _run_in_thread() -> None:
        try:
            result, classification, needs_conf = await loop.run_in_executor(None, _plan_and_run)
            if needs_conf:
                payload: dict[str, Any] = {
                    "session_id": "",
                    "artifact_id": None,
                    "schema_valid": False,
                    "result": {},
                    "error": None,
                    "usage": None,
                    "classification": classification,
                    "needs_confirmation": True,
                }
            else:
                payload = {
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
                    "classification": classification,
                    "needs_confirmation": False,
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
