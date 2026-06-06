"""Tests for the iteration engine (PR-27)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opspilot.iteration.engine import IterationEngine
from opspilot.iteration.feedback import aggregate_signals, load_signals
from opspilot.iteration.types import FeedbackSignal, IterationPolicy

EXAMPLE_DIR = Path(__file__).parents[1] / "examples" / "itr_ticket_summary_zh_v1_3_0"
SIGNALS_FILE = EXAMPLE_DIR / "feedback" / "signals.jsonl"


# ── Feedback aggregation ───────────────────────────────────────────────────


def test_load_signals_count():
    signals = load_signals(SIGNALS_FILE)
    assert len(signals) == 5


def test_load_signals_types():
    signals = load_signals(SIGNALS_FILE)
    edits = [s for s in signals if s.signal_type == "user_action.edit"]
    patterns = [s for s in signals if s.signal_type == "distillation_pattern"]
    assert len(edits) == 4
    assert len(patterns) == 1


def test_aggregate_weight_matches_example():
    """Aggregate weight should be 5.5 (Σ|w_i| = 4×1.0 + 1×1.5), matching the README."""
    signals = load_signals(SIGNALS_FILE)
    policy = IterationPolicy()
    # Evaluate as of 2026-05-01 (all signals are within 30-day window)
    as_of = datetime(2026, 5, 1, 13, 0, 0, tzinfo=UTC)
    result = aggregate_signals(signals, policy, as_of=as_of)

    assert result.signal_count == 5
    assert result.aggregate_weight == pytest.approx(5.5, abs=0.01)
    assert result.should_trigger is True
    assert result.threshold == 5.0


def test_aggregate_below_threshold():
    signals = [
        FeedbackSignal(
            id="fb_01AAAAAAAAAAAAAAAAAAAAAA01",
            skill_ref="test@1.0.0",
            ts=datetime(2026, 5, 1, tzinfo=UTC),
            signal_type="user_action.edit",
            weight=-1.0,
            redacted=True,
        )
    ]
    policy = IterationPolicy(feedback_min_weight_to_trigger=5.0)
    as_of = datetime(2026, 5, 1, 13, 0, 0, tzinfo=UTC)
    result = aggregate_signals(signals, policy, as_of=as_of)
    assert result.aggregate_weight == pytest.approx(1.0)
    assert result.should_trigger is False


def test_aggregate_excludes_expired():
    expired_ts = datetime(2026, 4, 1, tzinfo=UTC)
    signals = [
        FeedbackSignal(
            id="fb_01AAAAAAAAAAAAAAAAAAAAAA01",
            skill_ref="test@1.0.0",
            ts=datetime(2026, 4, 20, tzinfo=UTC),
            signal_type="user_action.edit",
            weight=-1.0,
            redacted=True,
            expires_at=expired_ts,  # already expired
        )
    ]
    policy = IterationPolicy()
    as_of = datetime(2026, 5, 1, tzinfo=UTC)
    result = aggregate_signals(signals, policy, as_of=as_of)
    assert result.signal_count == 0
    assert result.aggregate_weight == 0.0
    assert result.should_trigger is False


# ── Variant evaluation ─────────────────────────────────────────────────────


def test_evaluate_verdicts():
    engine = IterationEngine()
    verdicts = engine.evaluate(EXAMPLE_DIR)

    assert len(verdicts) == 2
    by_id = {v.variant_id: v for v in verdicts}

    assert by_id["var_9930d615"].gate.verdict == "winning"
    assert by_id["var_d373c759"].gate.verdict == "losing"


def test_evaluate_winning_delta():
    engine = IterationEngine()
    verdicts = engine.evaluate(EXAMPLE_DIR)
    winner = next(v for v in verdicts if v.variant_id == "var_9930d615")
    assert winner.delta.weighted == pytest.approx(0.014, abs=0.001)
    assert winner.delta.cost_pct == pytest.approx(4.5, abs=0.1)


def test_evaluate_losing_cost_gate():
    engine = IterationEngine()
    verdicts = engine.evaluate(EXAMPLE_DIR)
    loser = next(v for v in verdicts if v.variant_id == "var_d373c759")
    assert loser.gate.max_cost_increase_pct_pass is False
    assert loser.delta.cost_pct == pytest.approx(18.3, abs=0.1)


# ── Validate ──────────────────────────────────────────────────────────────


def test_validate_example_passes():
    engine = IterationEngine()
    violations = engine.validate(EXAMPLE_DIR)
    # All checksums and IDs in the example should be valid
    assert violations == []


# ── Engine sense integration ──────────────────────────────────────────────


def test_engine_sense():
    engine = IterationEngine()
    # Pin the reference time so the fixed-date fixture stays inside the 30-day
    # feedback window regardless of when the test runs.
    as_of = datetime(2026, 5, 1, 13, 0, 0, tzinfo=UTC)
    result = engine.sense(SIGNALS_FILE, as_of=as_of)
    assert result.should_trigger is True
    assert result.aggregate_weight >= 5.0
