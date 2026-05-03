"""GET /api/config route."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..types import ApiConfigResponse

router = APIRouter()


@router.get("/config", response_model=ApiConfigResponse)
def get_config(request: Request) -> ApiConfigResponse:
    """Return the active model reference and enabled UI modules."""
    return ApiConfigResponse(
        active_model_ref=request.app.state.active_model_ref,
        modules=request.app.state.cfg.ui_modules,
    )
