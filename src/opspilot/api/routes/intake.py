"""POST /api/intake — generic inbound webhook intake (ADR-0015).

Push counterpart to the polling Source adapters: any system that can send
an HTTP request files a Work item. The endpoint accepts fast (webhook
senders time out long before an LLM run finishes), dedupes by key, and
processes in the background; results land as normal Sessions. Write-back
stays with the polling adapters — a pusher has no comment destination.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response

from ..types import ApiIntakeRequest, ApiIntakeResponse, ApiRunRequest
from .run import run_ticket

logger = logging.getLogger("opspilot.api.intake")

router = APIRouter()


async def _process(body: ApiIntakeRequest, request: Request) -> None:
    """Run one pushed Work item; mirrors the ADR-0013 loop semantics.

    A run that raises is forgotten (a redelivery retries it); a run that
    returns a deterministic outcome stays consumed.
    """
    run_body = ApiRunRequest(input=body.input, playbook_id=body.playbook_id, model_id=body.model_id)
    try:
        res = await run_ticket(run_body, request)
    except Exception:  # noqa: BLE001 — forget the key so a redelivery retries
        logger.exception("webhook intake run failed for %s (redelivery will retry)", body.key)
        request.app.state.intake_seen.discard(body.key)
        return
    if res.needs_confirmation:
        logger.warning("webhook intake %s withheld: classification needs confirmation", body.key)
    elif res.error:
        logger.warning("webhook intake %s failed: %s", body.key, res.error)
    else:
        logger.info("webhook intake %s → session %s", body.key, res.session_id)


@router.post("/intake", response_model=ApiIntakeResponse, status_code=202)
async def intake_work_item(
    body: ApiIntakeRequest,
    request: Request,
    background: BackgroundTasks,
    response: Response,
) -> ApiIntakeResponse:
    """Accept a pushed Work item, dedupe by key, run it in the background."""
    state = request.app.state
    seen: set[str] = getattr(state, "intake_seen", None) or set()
    state.intake_seen = seen
    if body.key in seen:
        response.status_code = 200
        return ApiIntakeResponse(accepted=False, duplicate=True, key=body.key)
    seen.add(body.key)
    background.add_task(_process, body, request)
    return ApiIntakeResponse(accepted=True, duplicate=False, key=body.key)
