"""Sandbox API routes: POST /api/sandbox/dry-run, POST /api/sandbox/run."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class SandboxRequest(BaseModel):
    action: dict[str, Any]
    force_approve: bool = False


@router.post("/sandbox/dry-run")
async def sandbox_dry_run(body: SandboxRequest, request: Request) -> dict[str, Any]:
    """Preview a sandbox action without executing it."""
    from ...sandbox.engine import SandboxEngine
    from ...sandbox.types import ActionRequest

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        req = ActionRequest.model_validate(body.action)
        result = SandboxEngine().dry_run(req)
        return result

    result = await loop.run_in_executor(None, _run)

    preview = None
    if result.dry_run_preview:
        preview = {
            "command_preview": result.dry_run_preview.command_preview,
            "docker_args": result.dry_run_preview.docker_args,
        }

    return {
        "action_id": result.action_id,
        "status": result.status,
        "approval_required": result.approval_required,
        "dry_run_preview": preview,
    }


@router.post("/sandbox/run")
async def sandbox_run(body: SandboxRequest, request: Request) -> dict[str, Any]:
    """Execute a sandbox action in a Docker L2 container."""
    from ...sandbox.engine import SandboxEngine
    from ...sandbox.types import ActionRequest

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        req = ActionRequest.model_validate(body.action)
        return SandboxEngine().execute(req, force_approve=body.force_approve)

    result = await loop.run_in_executor(None, _run)

    apply = None
    if result.apply_result:
        apply = {
            "exit_code": result.apply_result.exit_code,
            "stdout": result.apply_result.stdout,
            "stderr": result.apply_result.stderr,
            "duration_ms": result.apply_result.duration_ms,
        }

    return {
        "action_id": result.action_id,
        "status": result.status,
        "approval_required": result.approval_required,
        "rejection_reason": result.rejection_reason,
        "apply_result": apply,
    }
