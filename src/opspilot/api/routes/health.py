"""GET /health — liveness + readiness probe."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from opspilot import (
    __version__ as _VERSION,  # noqa: N812  (alias avoids rebinding this module's __version__)
)

router = APIRouter(tags=["ops"])

_START: float = time.monotonic()


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    cfg = request.app.state.cfg
    return {
        "status": "ok",
        "version": _VERSION,
        "uptime_seconds": int(time.monotonic() - _START),
        "home": str(cfg.home),
    }
