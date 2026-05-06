"""Vendor document API routes: generate and list stored docs."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
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


@router.post("/doc/generate", response_model=ApiRunResponse)
async def generate_vendor_doc(body: DocGenRequest, request: Request) -> ApiRunResponse:
    """Generate a vendor-facing operational document from KB content."""
    state = request.app.state
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
        import dataclasses
        effective_playbook = dataclasses.replace(pb, model=override_model, extra_models=[])
    else:
        effective_playbook = pb
        chat_provider = state.vendor_doc_provider

    input_dict: dict[str, Any] = {
        "topic": body.topic,
        "template_id": body.template_id,
        "vendor_name": body.vendor_name,
        "language": body.language,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(input_dict, f, ensure_ascii=False)
        input_path = Path(f.name)

    try:
        loop = asyncio.get_event_loop()
        orch_request = OrchestratorRunRequest(
            playbook=effective_playbook,
            input_path=input_path,
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
                user_msg_fn=_format_doc_request,
            )

        result = await loop.run_in_executor(None, _run)
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
                docs.append({
                    "filename": json_file.name,
                    "doc_ref": data.get("doc_ref", ""),
                    "template_id": data.get("template_id", ""),
                    "title": data.get("title", ""),
                    "scope_note": data.get("scope_note"),
                    "sections_count": len(data.get("sections") or []),
                    "citations_count": len(data.get("citations") or []),
                })
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
    return json.loads(json_file.read_text(encoding="utf-8"))
