"""Pydantic models for the OpsPilot API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiRunRequest(BaseModel):
    """Request body for POST /api/run."""

    input: dict[str, Any]  # raw ticket JSON
    playbook_id: str | None = None  # defaults to "pb_ticket_summary_zh"


class ApiRunResponse(BaseModel):
    """Response body for POST /api/run."""

    session_id: str
    artifact_id: str | None
    schema_valid: bool
    result: dict[str, Any]  # the ticket_summary_v1 artifact, or {} on error
    error: str | None


class ApiConfigResponse(BaseModel):
    """Response body for GET /api/config."""

    active_model_ref: str
    modules: dict[str, bool]
