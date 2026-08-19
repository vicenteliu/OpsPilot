"""Proposed actions: preview one, then a human runs it (ADR-0028).

A Session may put an action forward; **it runs only when a person presses
execute**. Automatic execution is not here, including for actions the approval
gate does not flag — the gate is a heuristic denylist and says so in its own
docstring, and it is not the thing that should decide whether something runs
unattended (ADR-0005).

The first batch is **read-only diagnostics**. That constraint lives in the
artifact schema, where `intent` is a const, so a mutating action cannot be
expressed; :mod:`opspilot.sandbox.proposals` refuses anything else as a second
line. What is being tuned first is proposal *quality*, and tuning that at the
same time as blast radius makes a failure impossible to attribute.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...auth import Identity, require_role
from ...sandbox import ProposalError, execute_proposal, preview_proposal
from ...session.types import TraceEvent

router = APIRouter()

_viewer = Depends(require_role("viewer"))
# Executing is an act. Reading a proposal is not.
_operator = Depends(require_role("operator"))


class ExecuteRequest(BaseModel):
    ref: str


def _proposals(request: Request, session_id: str) -> list[dict[str, Any]]:
    mgr = getattr(request.app.state, "session_mgr", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="session manager unavailable")
    try:
        store = mgr.artifacts(session_id)
        ids = store.list_ids()
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found") from exc
    if not ids:
        return []
    summary = json.loads(store.read_text(ids[0]))
    return list(summary.get("proposed_actions") or [])


def _engine(request: Request) -> Any:
    from ...sandbox import SandboxEngine

    return getattr(request.app.state, "sandbox", None) or SandboxEngine()


@router.get("/sessions/{session_id}/actions")
async def list_actions(
    session_id: str, request: Request, identity: Identity = _viewer
) -> dict[str, Any]:
    """What this Session proposed. Reading is not running."""
    return {"actions": _proposals(request, session_id)}


@router.post("/sessions/{session_id}/actions/{ref}/preview")
async def preview_action(
    session_id: str, ref: str, request: Request, identity: Identity = _viewer
) -> dict[str, Any]:
    """Dry-run it and show the gate's verdict. Nothing is applied.

    The verdict is computed here and never read from the proposal: a model that
    could set its own approval flag would be deciding whether it needs approval.
    """
    proposal = next((p for p in _proposals(request, session_id) if p.get("ref") == ref), None)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"no proposed action {ref!r}")

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        return preview_proposal(
            _engine(request), proposal, session_id=session_id, proposed_by="model:assistant"
        )

    try:
        result = await loop.run_in_executor(None, _run)
    except ProposalError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    _trace(
        request,
        session_id,
        "action_previewed",
        {"ref": ref, "approval_required": result.approval_required, "by": identity.name},
        identity.name,
    )
    return {
        "ref": result.ref,
        "command": result.request.payload.get("command", ""),
        "target": result.request.payload.get("target", ""),
        "why": result.request.description,
        "approval_required": result.approval_required,
        "dry_run_status": result.dry_run_status,
        "dry_run_stdout": result.dry_run_stdout,
    }


@router.post("/sessions/{session_id}/actions/execute")
async def execute_action(
    session_id: str, body: ExecuteRequest, request: Request, identity: Identity = _operator
) -> dict[str, Any]:
    """Run it, because a person said so.

    The actor is the caller's Identity and never the request body — the whole
    point of this step is that the trace can answer *who decided this ran*, and a
    self-reported answer is not evidence.
    """
    proposal = next((p for p in _proposals(request, session_id) if p.get("ref") == body.ref), None)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"no proposed action {body.ref!r}")

    mgr = request.app.state.session_mgr
    loop = asyncio.get_event_loop()

    def _run() -> Any:
        with mgr.trace(session_id) as tw:
            return execute_proposal(
                _engine(request),
                proposal,
                session_id=session_id,
                proposed_by="model:assistant",
                actor=identity.name,
                trace_writer=tw,
            )

    try:
        result = await loop.run_in_executor(None, _run)
    except ProposalError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # The output lives on `ActionResult.apply_result`, the way /api/sandbox
    # already reads it. Taken off the ActionResult these were silently None and
    # "" on every execution — and the output is the entire point of running a
    # diagnostic.
    applied = getattr(result, "apply_result", None)
    return {
        "ref": body.ref,
        "executed_by": identity.name,
        "status": str(getattr(result, "status", "unknown")),
        "exit_code": getattr(applied, "exit_code", None),
        "stdout": str(getattr(applied, "stdout", "") or "")[:20_000],
        "stderr": str(getattr(applied, "stderr", "") or "")[:8_000],
    }


def _trace(
    request: Request, session_id: str, event: Any, details: dict[str, Any], actor: str
) -> None:
    """Best-effort: a lost trace line must not fail the call it describes."""
    mgr = getattr(request.app.state, "session_mgr", None)
    if mgr is None:
        return
    with contextlib.suppress(Exception), mgr.trace(session_id) as tw:
        tw.write(TraceEvent.system(event=event, details=details, actor=actor))
