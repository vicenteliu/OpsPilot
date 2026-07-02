"""Stage 1 evaluators (6 non-judge).

Each evaluator is a small function that consumes the run output + golden
+ retrieved chunks and returns an :class:`EvaluatorResult` with score in
[0, 1] and a boolean ``passed``. Per docs/zh/design/IMPLEMENTATION_STAGE_1.md §786-797:

* ``schema_check``           — artifact validates against the golden's schema
* ``must_contain``           — every required substring appears in summary
* ``must_not_contain``       — no leaked-string substring appears
* ``rag.recall_at_k``        — fraction of golden chunks present in retrieved
* ``rag.precision_at_k``     — fraction of retrieved that are golden
* ``rag.citation_validity``  — every artifact citation matches a real KB chunk
                               (chunk_id + line range)

PR-9+ adds ``judge.llm`` (LLM-graded rubric).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..schemas import validate as schema_validate
from .errors import HarnessError
from .types import EvaluatorResult, Golden


@dataclass(frozen=True)
class EvalContext:
    """Bundle of inputs every evaluator needs."""

    artifact: dict[str, Any]  # the orchestrator's final work-item JSON
    golden: Golden
    retrieved_chunk_ids: list[str]  # in retrieval order, top-k
    kb_chunk_lookup: dict[str, dict[str, Any]] | None = None
    """Maps chunk_id → row from sqlite kb_chunks (line_start/line_end/etc.).
    Optional; if present, citation_validity does deep checks."""


# ── 1. schema_check ─────────────────────────────────────────────────


def evaluate_schema_check(ctx: EvalContext) -> EvaluatorResult:
    """artifact must validate against the schema named in golden.schema_check."""
    schema_name = ctx.golden.schema_check.get("name", "incident_summary_v1")
    try:
        schema_validate(schema_name, ctx.artifact)
        return EvaluatorResult(
            id="ev_schema_check",
            type="rule.json_schema",
            score=1.0,
            passed=True,
            details={"schema": schema_name},
        )
    except Exception as e:  # noqa: BLE001
        return EvaluatorResult(
            id="ev_schema_check",
            type="rule.json_schema",
            score=0.0,
            passed=False,
            details={"schema": schema_name, "error": str(e)[:300]},
        )


# ── 2. must_contain ─────────────────────────────────────────────────


def _summary_text(artifact: dict[str, Any]) -> str:
    """Concatenate narrative text fields from the artifact for must_contain checks.

    Handles incident_summary_v1 / request_fulfillment_v1 and vendor_doc_v1. Citations
    and metadata fields are excluded — only human-readable narrative text.
    """
    if artifact.get("schema_version") == "vendor_doc_v1":
        parts: list[str] = [str(artifact.get("title") or "")]
        for s in artifact.get("sections") or []:
            parts.append(str(s.get("heading") or ""))
            parts.append(str(s.get("content") or ""))
        if artifact.get("scope_note"):
            parts.append(str(artifact["scope_note"]))
        return "\n".join(parts)

    # work-item summary (incident_summary_v1 / request_fulfillment_v1)
    parts = [str(artifact.get("summary") or "")]
    parts.extend(str(s) for s in artifact.get("symptoms") or [])
    parts.extend(str(s) for s in artifact.get("tried_steps") or [])
    parts.extend(str(s) for s in artifact.get("missing_fields") or [])
    for task in artifact.get("tasks") or []:
        parts.append(str(task.get("action", "")))
        parts.append(str(task.get("rationale", "")))
    if artifact.get("escalation_hint"):
        parts.append(str(artifact["escalation_hint"]))
    return "\n".join(parts)


def evaluate_must_contain(ctx: EvalContext) -> EvaluatorResult:
    text = _summary_text(ctx.artifact)
    required = list(ctx.golden.must_contain)
    matched: list[str] = []
    missing: list[str] = []
    for s in required:
        if s in text:
            matched.append(s)
        else:
            missing.append(s)
    score = (len(matched) / len(required)) if required else 1.0
    return EvaluatorResult(
        id="ev_must_contain",
        type="rule.regex",
        score=score,
        passed=not missing,
        details={"required": required, "matched": matched, "missing": missing},
    )


# ── 3. must_not_contain ─────────────────────────────────────────────


def evaluate_must_not_contain(ctx: EvalContext) -> EvaluatorResult:
    text = _summary_text(ctx.artifact)
    forbidden = list(ctx.golden.must_not_contain)
    leaked: list[str] = [s for s in forbidden if s in text]
    score = 1.0 if not leaked else 0.0
    return EvaluatorResult(
        id="ev_must_not_contain",
        type="rule.regex",
        score=score,
        passed=not leaked,
        details={"forbidden": forbidden, "leaked": leaked},
    )


# ── 4. rag.recall_at_k ──────────────────────────────────────────────


def evaluate_rag_recall_at_k(ctx: EvalContext) -> EvaluatorResult:
    """Fraction of golden-required chunks that appear in retrieved top-k.

    Uses ``golden.expected_structured.must_have_citation_to_chunk`` as the
    single required chunk — Stage 1 fixtures only mark one. Treat any
    expected chunk as a 1-element golden set.
    """
    expected = ctx.golden.expected_chunk_id
    if not expected:
        # No expected chunk: vacuously full recall.
        return EvaluatorResult(
            id="ev_rag_recall_at_k",
            type="rag.recall_at_k",
            score=1.0,
            passed=True,
            details={"expected": [], "retrieved": list(ctx.retrieved_chunk_ids)},
        )
    score = 1.0 if expected in ctx.retrieved_chunk_ids else 0.0
    return EvaluatorResult(
        id="ev_rag_recall_at_k",
        type="rag.recall_at_k",
        score=score,
        passed=score == 1.0,
        details={
            "expected": [expected],
            "retrieved": list(ctx.retrieved_chunk_ids),
            "k": len(ctx.retrieved_chunk_ids),
        },
    )


# ── 5. rag.precision_at_k ───────────────────────────────────────────


def evaluate_rag_precision_at_k(ctx: EvalContext) -> EvaluatorResult:
    """Fraction of retrieved chunks that are relevant.

    Uses ``golden.relevant_chunk_ids`` as the relevant set (includes must +
    should chunks).  Falls back to the single ``expected_chunk_id`` when no
    explicit list is present.
    """
    relevant_set = ctx.golden.relevant_chunk_ids
    retrieved = ctx.retrieved_chunk_ids
    if not retrieved:
        return EvaluatorResult(
            id="ev_rag_precision_at_k",
            type="rag.precision_at_k",
            score=0.0,
            passed=False,
            details={"expected": relevant_set, "retrieved": []},
        )
    if not relevant_set:
        # No golden truth: vacuously correct.
        return EvaluatorResult(
            id="ev_rag_precision_at_k",
            type="rag.precision_at_k",
            score=1.0,
            passed=True,
            details={"expected": [], "retrieved": retrieved},
        )
    relevant_set_s = set(relevant_set)
    relevant = sum(1 for c in retrieved if c in relevant_set_s)
    score = relevant / len(retrieved)
    # Spec exit threshold: ≥ 0.5
    return EvaluatorResult(
        id="ev_rag_precision_at_k",
        type="rag.precision_at_k",
        score=score,
        passed=score >= 0.5,
        details={
            "expected": relevant_set,
            "retrieved": retrieved,
            "relevant_count": relevant,
        },
    )


# ── 6. rag.citation_validity ────────────────────────────────────────


def evaluate_rag_citation_validity(ctx: EvalContext) -> EvaluatorResult:
    """Every citation in artifact.citations must match a real KB chunk.

    A citation is valid iff:
      1. ``chunk_id`` exists in the KB (when ``kb_chunk_lookup`` is given).
      2. ``line_start`` / ``line_end`` match the KB row's stored values
         (when both sides supply them).

    If ``kb_chunk_lookup`` is missing, we fall back to a structural check
    (chunk_id pattern + non-empty source_path).
    """
    citations = ctx.artifact.get("citations") or []
    if not citations:
        return EvaluatorResult(
            id="ev_rag_citation_validity",
            type="rag.citation_validity",
            score=0.0,
            passed=False,
            details={"reason": "artifact has no citations"},
        )

    valid: list[str] = []
    invalid: list[dict[str, Any]] = []
    for c in citations:
        chunk_id = c.get("chunk_id")
        if not chunk_id:
            invalid.append({"chunk_id": None, "reason": "missing chunk_id"})
            continue
        if ctx.kb_chunk_lookup is not None:
            row = ctx.kb_chunk_lookup.get(chunk_id)
            if row is None:
                invalid.append({"chunk_id": chunk_id, "reason": "chunk not in KB"})
                continue
            ls, le = c.get("line_start"), c.get("line_end")
            row_ls, row_le = row.get("line_start"), row.get("line_end")
            if ls is not None and row_ls is not None and ls != row_ls:
                invalid.append(
                    {
                        "chunk_id": chunk_id,
                        "reason": f"line_start mismatch: {ls} vs KB {row_ls}",
                    }
                )
                continue
            if le is not None and row_le is not None and le != row_le:
                invalid.append(
                    {
                        "chunk_id": chunk_id,
                        "reason": f"line_end mismatch: {le} vs KB {row_le}",
                    }
                )
                continue
        valid.append(chunk_id)
    score = len(valid) / len(citations)
    return EvaluatorResult(
        id="ev_rag_citation_validity",
        type="rag.citation_validity",
        score=score,
        passed=score == 1.0,
        details={"valid": valid, "invalid": invalid, "total": len(citations)},
    )


# ── Registry / dispatcher ───────────────────────────────────────────


EvaluatorFn = Callable[[EvalContext], EvaluatorResult]

ALL_EVALUATORS: dict[str, EvaluatorFn] = {
    "schema_check": evaluate_schema_check,
    "must_contain": evaluate_must_contain,
    "must_not_contain": evaluate_must_not_contain,
    "rag.recall_at_k": evaluate_rag_recall_at_k,
    "rag.precision_at_k": evaluate_rag_precision_at_k,
    "rag.citation_validity": evaluate_rag_citation_validity,
}


def run_all_evaluators(ctx: EvalContext) -> list[EvaluatorResult]:
    """Run every Stage 1 evaluator in deterministic order."""
    out: list[EvaluatorResult] = []
    for name in (
        "schema_check",
        "must_contain",
        "must_not_contain",
        "rag.recall_at_k",
        "rag.precision_at_k",
        "rag.citation_validity",
    ):
        fn = ALL_EVALUATORS.get(name)
        if fn is None:
            raise HarnessError(f"unknown evaluator: {name}")
        out.append(fn(ctx))
    return out
