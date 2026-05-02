"""Harness — evaluation framework + golden tests.

PR-8 ships:

* :class:`Fixture` / :class:`Golden` / :class:`EvalResult` — data
  contracts mirroring ``harness/schemas/*.schema.json``.
* 6 evaluators (no judge.llm in Stage 1; D1 of PR-8 plan):
  ``schema_check``, ``must_contain``, ``must_not_contain``,
  ``rag.recall_at_k``, ``rag.precision_at_k``, ``rag.citation_validity``.
* :func:`run_harness` — drives a single fixture through the orchestrator
  and emits a schema-valid :class:`EvalResult` row.
* CLI: ``opspilot harness run`` and ``opspilot harness golden``.

Closes Stage 1's exit criterion:
``IMPLEMENTATION_STAGE_1.md §786-797`` — make golden passes with
weighted_score ≥ 0.85 against the spec example.
"""

from .errors import HarnessError
from .runner import run_harness
from .types import (
    DEFAULT_EVALUATOR_WEIGHTS,
    EvalResult,
    EvaluatorResult,
    EvaluatorSpec,
    Fixture,
    Golden,
    Rubric,
    load_fixture,
    load_golden,
    load_rubric,
)

__all__ = [
    "DEFAULT_EVALUATOR_WEIGHTS",
    "EvalResult",
    "EvaluatorResult",
    "EvaluatorSpec",
    "Fixture",
    "Golden",
    "HarnessError",
    "Rubric",
    "load_fixture",
    "load_golden",
    "load_rubric",
    "run_harness",
]
