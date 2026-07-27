"""Pydantic models for the OpsPilot API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiRunRequest(BaseModel):
    """Request body for POST /api/run."""

    input: dict[str, Any]  # raw ticket JSON
    playbook_id: str | None = None  # defaults to "pb_ticket_summary_en"
    model_id: str | None = (
        None  # e.g. "anthropic/claude-haiku-4-5-20251001"; None = playbook default
    )


class ApiIntakeRequest(BaseModel):
    """Request body for POST /api/intake (webhook intake, ADR-0015)."""

    key: str  # source-unique id used for dedupe, e.g. "MON-1042"
    input: dict[str, Any]  # raw work item JSON, same shape as ApiRunRequest.input
    playbook_id: str | None = None
    model_id: str | None = None


class ApiIntakeResponse(BaseModel):
    """Response body for POST /api/intake."""

    accepted: bool
    duplicate: bool
    key: str


class ApiAssetCreate(BaseModel):
    """Request body for POST /api/inventory (ADR-0017)."""

    asset_tag: str = ""
    category: str = ""
    brand_model: str = ""
    serial_number: str = ""
    specs: str = ""
    notes: str = ""
    work_item_ref: str = ""
    pr_number: str = ""
    order_number: str = ""
    tracking_number: str = ""
    vendor: str = ""
    cost: str = ""
    status: str = "requested"
    handler: str = ""
    assignee: str = ""
    location: str = ""
    warranty_until: str = ""
    note: str = ""  # free-text annotation; the actor comes from the caller's identity


class ApiAssetUpdate(BaseModel):
    """Request body for PATCH /api/inventory/{asset_id}; None = unchanged."""

    asset_tag: str | None = None
    category: str | None = None
    brand_model: str | None = None
    serial_number: str | None = None
    specs: str | None = None
    notes: str | None = None
    work_item_ref: str | None = None
    pr_number: str | None = None
    order_number: str | None = None
    tracking_number: str | None = None
    vendor: str | None = None
    cost: str | None = None
    status: str | None = None
    handler: str | None = None
    assignee: str | None = None
    location: str | None = None
    warranty_until: str | None = None
    note: str = ""


class ApiAsset(BaseModel):
    """One Asset row (the projection; history lives in the events)."""

    asset_id: str
    asset_tag: str
    category: str
    brand_model: str
    serial_number: str
    specs: str
    notes: str
    work_item_ref: str
    pr_number: str
    order_number: str
    tracking_number: str
    vendor: str
    cost: str
    status: str
    handler: str
    assignee: str
    location: str
    warranty_until: str
    procurement_id: str = ""  # set via the grouping endpoints, not PATCH (#87)
    created_at: str
    updated_at: str


class ApiProcurementCreate(BaseModel):
    """Request body for POST /api/inventory/procurements — group existing Assets."""

    asset_ids: list[str]


class ApiProcurementUpdate(BaseModel):
    """PATCH body; a change syncs to every member Asset. None = unchanged."""

    pr_number: str | None = None
    order_number: str | None = None
    tracking_number: str | None = None
    vendor: str | None = None
    cost: str | None = None


class ApiProcurement(BaseModel):
    procurement_id: str
    pr_number: str
    order_number: str
    tracking_number: str
    vendor: str
    cost: str
    created_at: str
    updated_at: str
    member_count: int


class ApiProcurementDetail(ApiProcurement):
    members: list[ApiAsset]


class ApiProcurementListResponse(BaseModel):
    procurements: list[ApiProcurement]


class ApiAssetEvent(BaseModel):
    event_id: int
    ts: str
    actor: str
    change: str
    note: str


class ApiInventoryEvent(ApiAssetEvent):
    """An event in the cross-Asset feed, where the Asset may no longer exist."""

    asset_id: str


class ApiInventoryEventListResponse(BaseModel):
    events: list[ApiInventoryEvent]


class ApiAssetDetail(ApiAsset):
    """Response body for GET /api/inventory/{asset_id}."""

    events: list[ApiAssetEvent]


class ApiAssetListResponse(BaseModel):
    """Response body for GET /api/inventory."""

    assets: list[ApiAsset]


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

    session_id: str  # "" when needs_confirmation (no run happened)
    artifact_id: str | None
    schema_valid: bool
    result: dict[str, Any]  # the work-item artifact, or {} on error / confirmation
    error: str | None
    usage: ApiTokenUsage | None = None
    # Work item classification (#6). Present when the type was inferred rather
    # than declared. needs_confirmation=True means the run was withheld pending a
    # human pick (low confidence); re-submit with an explicit playbook_id.
    classification: dict[str, Any] | None = None
    needs_confirmation: bool = False
    # Asset ids drafted from this run's asset_draft block (ADR-0018).
    assets_drafted: list[str] = []


class ApiConfigResponse(BaseModel):
    """Response body for GET /api/config."""

    active_model_ref: str
    modules: dict[str, bool]
    # Active embedding backend + a notice when it fell back (ADR-0020).
    embed_provider: str = "ollama"
    embed_warning: str | None = None


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
