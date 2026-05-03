"""POST /api/run route."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from ...orchestrator.ticket_summary import run_ticket_summary
from ...orchestrator.types import RunRequest as OrchestratorRunRequest
from ...providers.registry import make_provider
from ..types import ApiRunRequest, ApiRunResponse, ApiTokenUsage

router = APIRouter()


@router.post("/run", response_model=ApiRunResponse)
async def run_ticket(body: ApiRunRequest, request: Request) -> ApiRunResponse:
    """Accept a ticket JSON and run the ticket summary playbook."""
    state = request.app.state
    pb = state.playbook

    # Resolve which provider + playbook spec to use.
    # model_id = None or matching the primary → use startup provider as-is.
    # model_id matching any extra_model → promote that model to primary for this run.
    primary_id = f"{pb.model.provider_id}/{pb.model.name}"
    override_model = next(
        (m for m in pb.extra_models if f"{m.provider_id}/{m.name}" == body.model_id),
        None,
    ) if body.model_id and body.model_id != primary_id else None

    if override_model is not None:
        cfg = state.cfg
        override_provider = make_provider(
            override_model.provider_id,
            kind=override_model.kind,
            api_key=cfg.anthropic_api_key if override_model.kind == "anthropic" else None,
            base_url=cfg.ollama_base_url if override_model.kind == "ollama" else None,
        )
        override_retrieval_mode = "prefetch" if override_model.kind == "ollama" else pb.retrieval.mode
        effective_playbook = dataclasses.replace(
            pb,
            model=override_model,
            extra_models=[],
            retrieval=dataclasses.replace(pb.retrieval, mode=override_retrieval_mode),
        )
        chat_provider = override_provider
    else:
        # Default: use the primary model.
        effective_playbook = pb
        chat_provider = state.chat_provider

    # Write ticket to a temp file so the orchestrator can read it.
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
