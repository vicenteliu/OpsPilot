"""Harness runner — drive a fixture through the orchestrator + evaluators.

Flow::

    fixture + golden + playbook
        ↓
    write fixture.input as ticket.json (ephemeral)
        ↓
    run_ticket_summary(...)  →  RunResult (artifact + session_id)
        ↓
    extract retrieved chunk_ids from session trace.jsonl
        ↓
    build EvalContext + run all 6 evaluators
        ↓
    weighted_score → pass/fail
        ↓
    EvalResult (schema-valid against eval-result.schema.json)
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..ids import new_ulid_id
from ..memory.lance_store import LanceStore
from ..memory.sqlite_store import SqliteStore
from ..observability import record_harness
from ..orchestrator import RunRequest, RunResult, run_ticket_summary
from ..orchestrator.types import PlaybookSpec
from ..providers.base import ProviderProtocol
from ..redaction import Redactor
from ..session.manager import SessionManager
from ..timeutil import now_rfc3339
from .evaluators import EvalContext, run_all_evaluators
from .types import (
    DEFAULT_EVALUATOR_WEIGHTS,
    WEIGHTED_SCORE_PASS_THRESHOLD,
    EvalResult,
    EvaluatorResult,
    Fixture,
    Golden,
)


def run_harness(
    *,
    fixture: Fixture,
    golden: Golden,
    playbook: PlaybookSpec,
    session_manager: SessionManager,
    provider: ProviderProtocol,
    redactor: Redactor,
    embed_fn: Callable[[str], list[float]],
    sqlite_store: SqliteStore,
    lance_store: LanceStore,
    owner: str = "harness@opspilot",
    weights: dict[str, float] | None = None,
    pass_threshold: float = WEIGHTED_SCORE_PASS_THRESHOLD,
    tmp_dir: Path | None = None,
    user_msg_fn: Callable[[dict], str] | None = None,
) -> EvalResult:
    """Run one fixture end-to-end and return its :class:`EvalResult`."""
    weights = weights or DEFAULT_EVALUATOR_WEIGHTS
    tmp_dir = tmp_dir or Path("/tmp/opspilot-harness")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    run_id = new_ulid_id("run")
    started_at = now_rfc3339()
    started_perf = time.perf_counter()

    # ── 1. Stage the fixture's input as ticket.json ─────────────────
    ticket_path = tmp_dir / f"{fixture.id}.json"
    ticket_path.write_text(json.dumps(fixture.input, ensure_ascii=False), encoding="utf-8")

    # ── 2. Run the orchestrator ─────────────────────────────────────
    request = RunRequest(
        playbook=playbook,
        input_path=ticket_path,
        owner=owner,
    )
    run_result: RunResult = run_ticket_summary(
        request,
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=embed_fn,
        sqlite_store=sqlite_store,
        lance_store=lance_store,
        user_msg_fn=user_msg_fn,
    )

    # ── 3. Extract retrieved chunk_ids from trace.jsonl ─────────────
    retrieved_chunk_ids = _retrieved_chunks(session_manager.session_dir(run_result.session_id))

    # ── 4. Build KB lookup so citation_validity can deep-check ──────
    kb_lookup = _build_kb_lookup(sqlite_store, run_result, retrieved_chunk_ids)

    # ── 5. Run evaluators ───────────────────────────────────────────
    ctx = EvalContext(
        artifact=run_result.summary,
        golden=golden,
        retrieved_chunk_ids=retrieved_chunk_ids,
        kb_chunk_lookup=kb_lookup,
    )
    eval_results: list[EvaluatorResult] = run_all_evaluators(ctx)

    # ── 6. Aggregate weighted score ────────────────────────────────
    # eval-result.schema.json constrains scores = {weighted, by_type}; nest
    # per-evaluator scores under by_type rather than flattening at top level.
    by_type: dict[str, float] = {er.id: er.score for er in eval_results}
    weighted = _weighted_score(eval_results, weights)
    scores: dict[str, Any] = {"weighted": weighted, "by_type": by_type}
    # Per IMPLEMENTATION_STAGE_1.md §9.1 the pass gate is weighted_score
    # alone; individual evaluator passed flags are surfaced for triage but
    # don't dominate the final verdict (e.g. precision@k can be < 0.5 in
    # tiny KBs with only 1 relevant chunk).
    passed = weighted >= pass_threshold

    # ── 7. Build EvalResult ─────────────────────────────────────────
    duration_ms = int((time.perf_counter() - started_perf) * 1000)
    # eval-result.schema.json constrains `flags` to a fixed enum
    # (nondeterministic / redaction_warning / judge_low_confidence /
    # manual_review_pending / cost_gate_failed). Orchestrator-level
    # diagnostics surface in extensions instead so they don't violate
    # the schema for an otherwise-valid (failing) run.
    flags: list[str] = []
    extensions: dict[str, Any] = {}
    if not run_result.schema_valid or run_result.error:
        flags.append("manual_review_pending")
        extensions["orchestrator"] = {
            "schema_valid": run_result.schema_valid,
            "error": run_result.error,
        }

    record_harness(provider=playbook.model.provider_id, passed=passed)

    return EvalResult(
        run_id=run_id,
        fixture_id=fixture.id,
        fixture_version=fixture.version,
        playbook_ref=f"{playbook.id}@{playbook.version}",
        model_ref=(f"{playbook.model.provider_id}/{playbook.model.name}@{playbook.model.version}"),
        ts=started_at,
        output={
            "inline": None,
            "artifact_id": run_result.artifact_id,
            "session_id": run_result.session_id,
        },
        evaluators=eval_results,
        scores=scores,
        passed=passed,
        flags=flags,
        latency_ms={"total": duration_ms},
        extensions=extensions,
    )


# ── Helpers ─────────────────────────────────────────────────────────


def _retrieved_chunks(session_dir: Path) -> list[str]:
    """Walk trace.jsonl tool_result rows and harvest chunk_ids in order.

    Deduplicates while preserving first-seen order (since multiple
    kb_search calls may return overlapping chunks).
    """
    trace_path = session_dir / "trace.jsonl"
    if not trace_path.is_file():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "tool_result":
            continue
        if row.get("tool") != "kb_search":
            continue
        stdout = row.get("stdout_ref") or ""
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            continue
        for h in payload.get("hits") or []:
            cid = h.get("chunk_id")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(cid)
    return out


def _build_kb_lookup(
    sqlite_store: SqliteStore,
    run_result: RunResult,
    retrieved_chunk_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Fetch line_start/line_end for every chunk citation_validity may check.

    We pull from both:
      * retrieved_chunk_ids (so we can resolve any citation that came from
        actual retrieval)
      * artifact.citations[*].chunk_id (so cross-checks fire on synthesised
        IDs the LLM might invent)
    """
    wanted: set[str] = set(retrieved_chunk_ids)
    for c in (run_result.summary or {}).get("citations") or []:
        if isinstance(c, dict) and c.get("chunk_id"):
            wanted.add(str(c["chunk_id"]))
    out: dict[str, dict[str, Any]] = {}
    for cid in wanted:
        row = sqlite_store.get_chunk(cid)
        if row is not None:
            out[cid] = row
    return out


def _weighted_score(
    eval_results: list[EvaluatorResult],
    weights: dict[str, float],
) -> float:
    """Sum (score * weight) where weight is keyed on ``EvaluatorResult.type``.

    The default weights live in :data:`DEFAULT_EVALUATOR_WEIGHTS` and key on
    canonical evaluator names ("schema_check", "must_contain", "rag.recall_at_k",
    ...). We map evaluator types onto those keys.
    """
    type_to_key: dict[str, str | None] = {
        "rule.json_schema": "schema_check",
        "rule.regex": None,  # need to look at id to disambiguate must_*
        "rag.recall_at_k": "rag.recall_at_k",
        "rag.precision_at_k": "rag.precision_at_k",
        "rag.citation_validity": "rag.citation_validity",
    }
    total = 0.0
    for er in eval_results:
        key = type_to_key.get(er.type)
        if key is None:
            # rule.regex disambiguation by id
            if "must_contain" in er.id and "not" not in er.id:
                key = "must_contain"
            elif "must_not_contain" in er.id:
                key = "must_not_contain"
            else:
                key = er.type
        weight = float(weights.get(key, 0.0))
        total += er.score * weight
    return round(total, 4)
