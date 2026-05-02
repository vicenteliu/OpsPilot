"""Data contracts for the evaluation harness.

Three primary objects from spec ``harness/schemas/``:

* :class:`Fixture` — one test case (input + tags + scenario).
* :class:`Golden`  — expected output + must_contain / must_not_contain
  rules + schema_check spec; pulled from ``examples/.../harness/golden.json``.
* :class:`EvalResult` — emitted by the runner; conforms to
  ``eval-result.schema.json``.

Plus :class:`EvaluatorSpec` (id + type + weight + config) and
:class:`Rubric` (lightweight dict around ``rubric.md``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .errors import HarnessError

# ── Defaults ────────────────────────────────────────────────────────


DEFAULT_EVALUATOR_WEIGHTS: Final[dict[str, float]] = {
    "schema_check": 0.40,
    "must_contain": 0.20,
    "must_not_contain": 0.10,
    "rag.recall_at_k": 0.15,
    "rag.precision_at_k": 0.05,
    "rag.citation_validity": 0.10,
}
"""Per D5 of the PR-8 plan: 0.4 schema + 0.2 must_contain + 0.1 must_not_contain
+ 0.15 rag_recall + 0.05 rag_precision + 0.1 citation_validity. Sums to 1.0."""


WEIGHTED_SCORE_PASS_THRESHOLD: Final[float] = 0.85


# ── Spec mirrors ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Fixture:
    """One test case (mirrors ``harness/schemas/fixture.schema.json``)."""

    id: str
    scenario_id: str
    version: str
    title: str
    description: str
    tags: list[str]
    language: str
    input: dict[str, Any]
    content_hash: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Fixture:
        d = {k: v for k, v in d.items() if k != "_comment"}
        return cls(
            id=d["id"],
            scenario_id=d["scenario_id"],
            version=d["version"],
            title=d.get("title", ""),
            description=d.get("description", ""),
            tags=list(d.get("tags") or []),
            language=d.get("language", "und"),
            input=dict(d["input"]),
            content_hash=d.get("content_hash"),
        )


@dataclass(frozen=True)
class Golden:
    """Expected output + assertions for a fixture.

    Mirrors ``examples/.../harness/golden.json`` shape (no spec schema for
    golden itself yet — it's an adapter contract). PR-8 only consumes the
    fields the 6 Stage 1 evaluators need.
    """

    id: str
    fixture_id: str
    scenario_id: str
    version: str
    must_contain: list[str]
    must_not_contain: list[str]
    schema_check: dict[str, Any]
    expected_structured: dict[str, Any]
    expected_summary_nl: str | None = None
    rubric_ref: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Golden:
        d = {k: v for k, v in d.items() if k != "_comment"}
        return cls(
            id=d["id"],
            fixture_id=d["fixture_id"],
            scenario_id=d["scenario_id"],
            version=d.get("version", "1.0.0"),
            must_contain=list(d.get("must_contain") or []),
            must_not_contain=list(d.get("must_not_contain") or []),
            schema_check=dict(d.get("schema_check") or {}),
            expected_structured=dict(d.get("expected_structured") or {}),
            expected_summary_nl=d.get("expected_summary_nl"),
            rubric_ref=d.get("rubric_ref"),
        )

    @property
    def expected_chunk_id(self) -> str | None:
        """``must_have_citation_to_chunk`` if present in expected_structured."""
        v = self.expected_structured.get("must_have_citation_to_chunk")
        if isinstance(v, str):
            return v
        return None


@dataclass(frozen=True)
class Rubric:
    """Container for an associated ``rubric.md`` (free-form markdown).

    PR-8 doesn't parse rubric content — it's only here so the eval-result
    can reference the source. PR-9+ (judge.llm) will actually use it.
    """

    path: Path
    content: str


# ── Evaluator contracts ─────────────────────────────────────────────


@dataclass(frozen=True)
class EvaluatorSpec:
    """One row in run-config.yaml#/evaluators."""

    id: str
    type: str
    weight: float
    hard_fail: bool = False
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluatorResult:
    """Output of a single evaluator's :meth:`evaluate`."""

    id: str
    type: str
    score: float  # [0, 1]
    passed: bool  # name avoids shadowing the Python builtin
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "score": self.score,
            "pass": self.passed,
            "details": dict(self.details),
        }


# ── EvalResult (per harness/schemas/eval-result.schema.json) ────────


@dataclass(frozen=True)
class EvalResult:
    """One row in results.jsonl.

    ``scores`` matches the schema's ``{weighted, by_type}`` shape; helpers
    are exposed to read either piece without callers having to know the
    nesting layout.
    """

    run_id: str
    fixture_id: str
    fixture_version: str
    playbook_ref: str
    model_ref: str
    ts: str
    evaluators: list[EvaluatorResult]
    scores: dict[str, Any]
    passed: bool
    output: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    latency_ms: dict[str, Any] = field(default_factory=dict)

    @property
    def weighted_score(self) -> float:
        return float(self.scores.get("weighted", 0.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "fixture_id": self.fixture_id,
            "fixture_version": self.fixture_version,
            "playbook_ref": self.playbook_ref,
            "model_ref": self.model_ref,
            "ts": self.ts,
            "output": dict(self.output),
            "evaluators": [e.to_dict() for e in self.evaluators],
            "scores": dict(self.scores),
            "pass": self.passed,
            "flags": list(self.flags),
            "latency_ms": dict(self.latency_ms),
        }


# ── Loaders ─────────────────────────────────────────────────────────


def load_fixture(path: Path) -> Fixture:
    if not path.is_file():
        raise HarnessError(f"fixture not found: {path}")
    return Fixture.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_golden(path: Path) -> Golden:
    if not path.is_file():
        raise HarnessError(f"golden not found: {path}")
    return Golden.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_rubric(path: Path) -> Rubric:
    if not path.is_file():
        raise HarnessError(f"rubric not found: {path}")
    return Rubric(path=path, content=path.read_text(encoding="utf-8"))
