"""GET /metrics — Prometheus text format."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ..middleware import metrics_text

router = APIRouter(tags=["ops"])


@router.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return metrics_text()
