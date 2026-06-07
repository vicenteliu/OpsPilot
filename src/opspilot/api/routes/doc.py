"""Vendor document API routes: generate and list stored docs."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...orchestrator.ticket_summary import _format_doc_request, run_ticket_summary
from ...orchestrator.types import RunRequest as OrchestratorRunRequest
from ...providers.registry import make_provider
from ..types import ApiRunResponse, ApiTokenUsage

router = APIRouter()


class DocGenRequest(BaseModel):
    topic: str
    template_id: str = "sop_summary"
    vendor_name: str = ""
    language: str = "en"
    model_id: str | None = None


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _resolve_doc_provider_and_playbook(body: DocGenRequest, state: Any) -> tuple[Any, Any]:
    pb = state.vendor_doc_pb
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
        chat_provider = make_provider(
            override_model.provider_id,
            kind=override_model.kind,
            api_key=cfg.anthropic_api_key if override_model.kind == "anthropic" else None,
            base_url=cfg.ollama_base_url if override_model.kind == "ollama" else None,
        )
        effective_playbook = dataclasses.replace(pb, model=override_model, extra_models=[])
        return chat_provider, effective_playbook
    return state.vendor_doc_provider, pb


def _input_path_for(body: DocGenRequest) -> Path:
    input_dict: dict[str, Any] = {
        "topic": body.topic,
        "template_id": body.template_id,
        "vendor_name": body.vendor_name,
        "language": body.language,
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(input_dict, f, ensure_ascii=False)
        return Path(f.name)


@router.post("/doc/generate", response_model=ApiRunResponse)
async def generate_vendor_doc(body: DocGenRequest, request: Request) -> ApiRunResponse:
    """Generate a vendor-facing operational document from KB content (blocking)."""
    state = request.app.state
    chat_provider, effective_playbook = _resolve_doc_provider_and_playbook(body, state)
    input_path = _input_path_for(body)

    try:
        loop = asyncio.get_event_loop()
        orch_request = OrchestratorRunRequest(
            playbook=effective_playbook, input_path=input_path, owner="api:default"
        )

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
                user_msg_fn=_format_doc_request,
            ),
        )
    finally:
        input_path.unlink(missing_ok=True)

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


@router.post("/doc/generate/stream")
async def generate_vendor_doc_stream(body: DocGenRequest, request: Request) -> StreamingResponse:
    """Generate a vendor document, streaming SSE progress events then the final result."""
    state = request.app.state
    chat_provider, effective_playbook = _resolve_doc_provider_and_playbook(body, state)
    input_path = _input_path_for(body)

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def on_progress(msg: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "status", "message": msg})

    orch_request = OrchestratorRunRequest(
        playbook=effective_playbook, input_path=input_path, owner="api:default"
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
                    user_msg_fn=_format_doc_request,
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
                }
                if result.usage
                else None,
            }
            await queue.put({"type": "result", "data": payload})
        except Exception as exc:  # noqa: BLE001
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            input_path.unlink(missing_ok=True)

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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/vendor-docs")
async def list_vendor_docs(request: Request) -> dict[str, Any]:
    """List all stored vendor docs from ~/.opspilot/vendor-docs/."""
    cfg = request.app.state.cfg
    vd_dir = cfg.home / "vendor-docs"

    docs = []
    if vd_dir.is_dir():
        for json_file in sorted(vd_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                docs.append(
                    {
                        "filename": json_file.name,
                        "doc_ref": data.get("doc_ref", ""),
                        "template_id": data.get("template_id", ""),
                        "title": data.get("title", ""),
                        "scope_note": data.get("scope_note"),
                        "sections_count": len(data.get("sections") or []),
                        "citations_count": len(data.get("citations") or []),
                    }
                )
            except Exception:  # noqa: BLE001
                pass
    return {"docs": docs, "total": len(docs)}


@router.get("/vendor-docs/{filename}")
async def get_vendor_doc(filename: str, request: Request) -> dict[str, Any]:
    """Return full vendor doc JSON for the given filename."""
    from fastapi import HTTPException

    cfg = request.app.state.cfg
    vd_dir = cfg.home / "vendor-docs"
    json_file = vd_dir / filename
    if not json_file.is_file() or json_file.suffix != ".json":
        raise HTTPException(status_code=404, detail=f"Vendor doc '{filename}' not found")
    return cast("dict[str, Any]", json.loads(json_file.read_text(encoding="utf-8")))
