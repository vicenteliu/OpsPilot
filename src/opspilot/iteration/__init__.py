"""Iteration engine — feedback aggregation, variant evaluation, promotion, lineage."""

from .engine import IterationEngine
from .feedback import aggregate_signals, load_signals
from .types import AggregateResult, IterationPolicy, VariantVerdict

__all__ = [
    "IterationEngine",
    "aggregate_signals",
    "load_signals",
    "AggregateResult",
    "IterationPolicy",
    "VariantVerdict",
]
