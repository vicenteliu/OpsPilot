"""GET /health — liveness + readiness probe."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from opspilot import __version__ as _VERSION

router = APIRouter(tags=["ops"])

_START: float = time.monotonic()


@router.get("/health")
def health(request: Request) -> dict:
    cfg = request.app.state.cfg
    return {
        "status": "ok",
        "version": _VERSION,
        "uptime_seconds": int(time.monotonic() - _START),
        "home": str(cfg.home),
    }
