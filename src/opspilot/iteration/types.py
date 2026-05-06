"""Iteration data types — feedback signals, policy, variants, verdicts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class FeedbackSignal(BaseModel):
    id: str
    skill_ref: str
    ts: datetime
    signal_type: str
    weight: float
    source: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    redacted: bool
    redaction_rules_version: str | None = None
    expires_at: datetime | None = None
    decay: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


class AggregateResult(BaseModel):
    skill_ref: str
    window_days: int
    as_of: datetime
    signal_count: int
    aggregate_weight: float
    should_trigger: bool
    threshold: float
    signal_ids: list[str]


class IterationPolicy(BaseModel):
    """Promotion criteria and trigger thresholds (mirrors iteration-policy.template.yaml defaults)."""

    feedback_min_weight_to_trigger: float = 5.0
    feedback_window_days: int = 30
    min_delta_weighted: float = 0.01
    max_cost_increase_pct: float = 10.0
    max_latency_p95_increase_pct: float = 20.0
    trigger_recall_min: float = 0.9
    trigger_fp_max: float = 0.05


class PromotionGateResult(BaseModel):
    min_delta_weighted_pass: bool
    no_regression_on_anchors_pass: bool
    max_cost_increase_pct_pass: bool
    trigger_eval_still_pass: bool
    static_checks_pass: bool
    verdict: Literal["winning", "losing"]


class VariantDelta(BaseModel):
    weighted: float
    cost_pct: float
    latency_p95_pct: float
    pass_rate: float = 0.0
    trigger_recall: float = 0.0
    trigger_false_positive: float = 0.0


class VariantVerdict(BaseModel):
    variant_id: str
    run_id: str
    delta: VariantDelta
    gate: PromotionGateResult
    verdict_reasons: list[str]


class LineageEntry(BaseModel):
    version: str
    parent: str | None
    iteration: str | None
    promoted_at: str
    promoted_by: str
    summary: str
    promoted_variant_id: str | None = None
    losing_variant_ids: list[str] = Field(default_factory=list)
    rollback_window_until: str | None = None
    rolled_back: bool = False
