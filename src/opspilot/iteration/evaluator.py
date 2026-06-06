"""Variant evaluator — apply promotion gates to pre-computed eval results."""

from __future__ import annotations

import json
from pathlib import Path

from .types import (
    IterationPolicy,
    PromotionGateResult,
    VariantDelta,
    VariantVerdict,
)


def load_eval_result(eval_file: Path) -> dict:
    return json.loads(eval_file.read_text(encoding="utf-8"))


def evaluate_variants(
    eval_dir: Path,
    variant_ids: list[str],
    policy: IterationPolicy,
) -> list[VariantVerdict]:
    """Load pre-computed eval/*.jsonl files and apply promotion gates."""
    verdicts = []
    for vid in variant_ids:
        result_file = eval_dir / f"{vid}-results.jsonl"
        if not result_file.exists():
            raise FileNotFoundError(f"Eval results not found: {result_file}")
        data = load_eval_result(result_file)
        verdicts.append(_apply_gates(data, policy))
    return verdicts


def _apply_gates(data: dict, policy: IterationPolicy) -> VariantVerdict:
    meta = data.get("iteration_meta", {})
    variant_id = meta.get("variant_id", data.get("run_id", "unknown"))
    run_id = data.get("run_id", "")

    raw_delta = meta.get("delta_vs_baseline", {})
    delta = VariantDelta(
        weighted=raw_delta.get("weighted", 0.0),
        cost_pct=raw_delta.get("cost_pct", 0.0),
        latency_p95_pct=raw_delta.get("latency_p95_pct", 0.0),
    )

    # Re-use embedded gate result if present; otherwise compute from policy
    embedded = meta.get("promotion_gate_result")
    if embedded:
        gate = PromotionGateResult(
            min_delta_weighted_pass=embedded["min_delta_weighted_pass"],
            no_regression_on_anchors_pass=embedded["no_regression_on_anchors_pass"],
            max_cost_increase_pct_pass=embedded["max_cost_increase_pct_pass"],
            trigger_eval_still_pass=embedded["trigger_eval_still_pass"],
            static_checks_pass=embedded["static_checks_pass"],
            verdict=embedded["verdict"],
        )
    else:
        gate = _compute_gate(delta, policy)

    reasons = _build_reasons(gate, delta, policy)
    return VariantVerdict(
        variant_id=variant_id, run_id=run_id, delta=delta, gate=gate, verdict_reasons=reasons
    )


def _compute_gate(delta: VariantDelta, policy: IterationPolicy) -> PromotionGateResult:
    delta_ok = delta.weighted >= policy.min_delta_weighted
    cost_ok = delta.cost_pct <= policy.max_cost_increase_pct
    # Anchors: no regression means pass_rate delta ≤ 0 (variant not worse)
    anchors_ok = delta.pass_rate >= 0.0
    trigger_ok = delta.trigger_recall >= 0.0 and delta.trigger_false_positive <= 0.0
    winning = delta_ok and cost_ok and anchors_ok and trigger_ok
    return PromotionGateResult(
        min_delta_weighted_pass=delta_ok,
        no_regression_on_anchors_pass=anchors_ok,
        max_cost_increase_pct_pass=cost_ok,
        trigger_eval_still_pass=trigger_ok,
        static_checks_pass=True,
        verdict="winning" if winning else "losing",
    )


def _build_reasons(
    gate: PromotionGateResult, delta: VariantDelta, policy: IterationPolicy
) -> list[str]:
    reasons = []
    if gate.no_regression_on_anchors_pass:
        reasons.append("no_regression_on_anchor: pass_rate unchanged")
    if gate.min_delta_weighted_pass:
        reasons.append(
            f"delta_weighted={delta.weighted} >= min_delta_weighted={policy.min_delta_weighted}"
        )
    else:
        reasons.append(
            f"delta_weighted={delta.weighted} < min_delta_weighted={policy.min_delta_weighted}"
        )
    if gate.max_cost_increase_pct_pass:
        reasons.append(
            f"cost growth +{delta.cost_pct}% <= max_cost_increase_pct={policy.max_cost_increase_pct}"
        )
    else:
        reasons.append(
            f"cost growth +{delta.cost_pct}% > max_cost_increase_pct={policy.max_cost_increase_pct}"
        )
    return reasons
