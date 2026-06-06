"""GET /metrics — Prometheus exposition (ADR-0007)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ...observability import render_metrics

router = APIRouter(tags=["ops"])


@router.get("/metrics")
def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
