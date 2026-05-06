"""Pydantic models for the OpsPilot API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiRunRequest(BaseModel):
    """Request body for POST /api/run."""

    input: dict[str, Any]  # raw ticket JSON
    playbook_id: str | None = None  # defaults to "pb_ticket_summary_zh"
    model_id: str | None = (
        None  # e.g. "anthropic/claude-haiku-4-5-20251001"; None = playbook default
    )


class ApiModelOption(BaseModel):
    """One selectable model in GET /api/models."""

    id: str  # "{provider_id}/{name}"
    label: str  # human-readable
    provider_id: str
    kind: str
    name: str
    retrieval_mode: str  # "tool" or "prefetch"


class ApiModelsResponse(BaseModel):
    """Response body for GET /api/models."""

    models: list[ApiModelOption]
    default_id: str


class ApiTokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ApiRunResponse(BaseModel):
    """Response body for POST /api/run."""

    session_id: str
    artifact_id: str | None
    schema_valid: bool
    result: dict[str, Any]  # the ticket_summary_v1 artifact, or {} on error
    error: str | None
    usage: ApiTokenUsage | None = None


class ApiConfigResponse(BaseModel):
    """Response body for GET /api/config."""

    active_model_ref: str
    modules: dict[str, bool]


class ApiSessionSummary(BaseModel):
    """One row in GET /api/sessions."""

    session_id: str
    created_at: str
    status: str
    artifact_id: str | None


class ApiSessionListResponse(BaseModel):
    """Response body for GET /api/sessions."""

    sessions: list[ApiSessionSummary]


class ApiLineageVersion(BaseModel):
    """One version entry in a skill's lineage."""

    version: str
    parent: str | None
    iteration: str | None
    promoted_at: str
    promoted_by: str
    summary: str
    promoted_variant_id: str | None = None
    losing_variant_ids: list[str] = []
    rollback_window_until: str | None = None
    rolled_back: bool = False


class ApiSkillLineage(BaseModel):
    """Lineage history for one skill."""

    skill_name: str
    versions: list[ApiLineageVersion]


class ApiLineageListResponse(BaseModel):
    """Response body for GET /api/iteration/lineage."""

    lineages: list[ApiSkillLineage]
