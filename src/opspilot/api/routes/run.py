"""POST /api/run route."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from ...orchestrator.ticket_summary import run_ticket_summary
from ...orchestrator.types import RunRequest as OrchestratorRunRequest
from ..types import ApiRunRequest, ApiRunResponse

router = APIRouter()


@router.post("/run", response_model=ApiRunResponse)
async def run_ticket(body: ApiRunRequest, request: Request) -> ApiRunResponse:
    """Accept a ticket JSON and run the ticket summary playbook."""
    state = request.app.state

    # Write ticket to a temp file so the orchestrator can read it.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(body.input, f, ensure_ascii=False)
        ticket_path = Path(f.name)

    try:
        loop = asyncio.get_event_loop()
        orch_request = OrchestratorRunRequest(
            playbook=state.playbook,
            input_path=ticket_path,
            owner="api:default",
        )

        # Run the synchronous orchestrator in a thread pool so we don't
        # block the event loop.
        def _run() -> Any:
            return run_ticket_summary(
                orch_request,
                session_manager=state.session_mgr,
                provider=state.chat_provider,
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
    )
