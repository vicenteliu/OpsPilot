"""GET /api/config route."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..types import ApiConfigResponse

router = APIRouter()


@router.get("/config", response_model=ApiConfigResponse)
def get_config(request: Request) -> ApiConfigResponse:
    """Return the active model reference, UI modules, and embedding status."""
    status = getattr(request.app.state, "embed_status", None)
    return ApiConfigResponse(
        active_model_ref=request.app.state.active_model_ref,
        modules=request.app.state.cfg.ui_modules,
        embed_provider=status.provider if status else "ollama",
        embed_warning=status.warning if status else None,
    )
