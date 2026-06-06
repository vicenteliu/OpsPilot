"""Feedback signal loading and aggregate weight computation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

from .types import AggregateResult, FeedbackSignal, IterationPolicy


def load_signals(signals_path: Path) -> list[FeedbackSignal]:
    signals = []
    for line in signals_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            signals.append(FeedbackSignal.model_validate(json.loads(line)))
    return signals


def aggregate_signals(
    signals: list[FeedbackSignal],
    policy: IterationPolicy,
    as_of: datetime | None = None,
) -> AggregateResult:
    """Compute Σ|w_i| for non-expired signals within the policy window.

    Uses absolute weight values (no decay) so 4×(-1.0) + 1.5 = 5.5, matching
    the iteration-policy.template.yaml threshold of 5.0.
    """
    if as_of is None:
        as_of = datetime.now(tz=UTC)

    cutoff_ts = as_of.timestamp() - policy.feedback_window_days * 86400

    in_window = [
        s
        for s in signals
        if _ts(s.ts) >= cutoff_ts
        and (s.expires_at is None or _ts(s.expires_at) > as_of.timestamp())
    ]

    aggregate_weight = sum(abs(s.weight) for s in in_window)
    skill_ref = in_window[0].skill_ref if in_window else (signals[0].skill_ref if signals else "")

    return AggregateResult(
        skill_ref=skill_ref,
        window_days=policy.feedback_window_days,
        as_of=as_of,
        signal_count=len(in_window),
        aggregate_weight=round(aggregate_weight, 4),
        should_trigger=aggregate_weight >= policy.feedback_min_weight_to_trigger,
        threshold=policy.feedback_min_weight_to_trigger,
        signal_ids=[s.id for s in in_window],
    )


def _ts(dt: datetime) -> float:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).timestamp()
    return dt.timestamp()
