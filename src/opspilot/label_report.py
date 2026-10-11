"""The label set's report: decision 2's engines measured on the labelled set (SPEC §7, #224).

Every engine answers every row three times. Each call is appended to a runs
file the moment it returns, so a run cut short resumes without paying for a
call twice, and the report can be recomputed from the file without calling
anything. A call that fails is recorded as a failure, retried on the next
run, and kept out of accuracy: an engine that could not answer was not wrong.

The report states, for each engine, accuracy and Brier score on all rows and
on the rows the labeller marked ``low``, cost per call and p50/p95 latency,
and the lowest probability at which the items it would route without a person
are at least 95% right (ADR-0040). It also states the relabel's agreement,
with the interval ten rows deserve. It writes nothing back to ``d2.yaml``:
setting the threshold is a decision taken on the report, not by it.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

from .errors import OpsPilotError
from .judgment import JudgmentEngine, Question
from .label_set import LABEL_SET_DIR, LabelSetError, _read_jsonl
from .orchestrator.ticket_summary import _format_ticket
from .redaction import Redactor

RUNS_PATH: Final = LABEL_SET_DIR / "runs_v1.jsonl"
RUNS: Final = 3
TARGET: Final = 0.95  # routed without a person, at least this right (ADR-0040)

Show = Callable[[str], None]


def row_state(row: dict[str, Any], redactor: Redactor) -> str:
    """The row as the run would show a Work item to an engine: formatted, then redacted.

    Only the subject, body and channel go in; the labels and what the drafter
    intended never do.
    """
    ticket = {
        "ticket_id": row["id"],
        "channel": row["channel"],
        "subject": row["subject"],
        "body": row["body"],
    }
    return redactor.redact(_format_ticket(ticket)).text


def _check_set(rows: list[dict[str, Any]], question: Question) -> None:
    if any(r["work_item_type"] is None for r in rows):
        raise LabelSetError("label every row first; the report measures the finished set")
    for r in rows:
        version = (r.get("answer_space") or {}).get(question.id)
        if version != question.version:
            raise LabelSetError(
                f"{r['id']} was labelled against {version}, not {question.version}; "
                "a changed answer space needs a relabel"
            )


def run_engines(
    rows: list[dict[str, Any]],
    question: Question,
    engines: Sequence[JudgmentEngine],
    *,
    runs: int = RUNS,
    out: Path = RUNS_PATH,
    redactor: Redactor,
    timeout_s: float,
    show: Show = lambda _: None,
) -> int:
    """Ask every engine every row, ``runs`` times; return how many calls this made."""
    _check_set(rows, question)
    done = (
        {(r["engine"], r["run"], r["id"]) for r in _read_jsonl(out) if r["error"] is None}
        if out.is_file()
        else set()
    )
    made = 0
    for engine in engines:
        for n in range(1, runs + 1):
            failed = 0
            for row in rows:
                if (engine.name, n, row["id"]) in done:
                    continue
                record: dict[str, Any] = {"engine": engine.name, "run": n, "id": row["id"]}
                started = time.monotonic()
                try:
                    j = engine.judge(question, row_state(row, redactor), timeout_s=timeout_s)
                    record |= {
                        "answer": j.answer,
                        "probability": j.probability,
                        "latency_ms": j.latency_ms,
                        "cost_usd": j.cost_usd,
                        "error": None,
                    }
                except OpsPilotError as e:
                    failed += 1
                    record |= {
                        "answer": None,
                        "probability": None,
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "cost_usd": 0.0,
                        "error": str(e),
                    }
                with out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                made += 1
            show(f"{engine.name} run {n}/{runs}: done" + (f", {failed} failed" if failed else ""))
    return made


# ── Measures ─────────────────────────────────────────────────────────────


def brier(judged: list[tuple[str, float, str]], *, positive: str) -> float:
    """Mean squared error of P(positive), from (answer, probability of it, label) triples."""
    total = 0.0
    for answer, p, label in judged:
        p_positive = p if answer == positive else 1 - p
        total += (p_positive - (1.0 if label == positive else 0.0)) ** 2
    return total / len(judged)


def threshold(judged: list[tuple[float, bool]]) -> tuple[float, int, int] | None:
    """The lowest probability whose items, routed alone, are at least 95% right.

    Returns the cut, how many items it routes and how many of those are right;
    None when no cut reaches the target.
    """
    for cut in sorted({p for p, _ in judged}):
        routed = [ok for p, ok in judged if p >= cut]
        if sum(routed) >= TARGET * len(routed):
            return cut, len(routed), sum(routed)
    return None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval for k successes in n trials."""
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


# ── The report ───────────────────────────────────────────────────────────


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def report_markdown(
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    relabels: list[dict[str, Any]] | None,
    question: Question,
) -> str:
    """The report SPEC §7 asks for, from the runs file and the relabel."""
    labels = {r["id"]: r["work_item_type"] for r in rows}
    low = {r["id"] for r in rows if r.get("label_confidence") == "low"}
    if stray := sorted({r["id"] for r in records} - labels.keys()):
        raise LabelSetError(f"the runs file answers rows the set does not have: {', '.join(stray)}")
    positive = next(iter(question.answers))
    engines = list(dict.fromkeys(r["engine"] for r in records))
    runs = max((r["run"] for r in records), default=0)

    lines = [
        f"# {question.version} on the label set: the engines compared",
        "",
        f"{len(rows)} rows is not a benchmark: synthetic, English, labelled by one person, and the"
        " threshold is set on the same rows it is reported on; there is no held-out split at this"
        f" size. Each engine answered every row {runs} times; accuracy and Brier pool the runs.",
        "",
        f"| Engine | Calls ok/failed | Accuracy | Across runs | Brier | Accuracy, low ({len(low)})"
        " | Brier, low | Cost/call | p50 | p95 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    cuts: list[str] = []
    for engine in engines:
        mine = [r for r in records if r["engine"] == engine]
        ok = [r for r in mine if r["error"] is None]
        right = [r["answer"] == labels[r["id"]] for r in ok]
        per_run = [
            sum(r["answer"] == labels[r["id"]] for r in ok if r["run"] == n)
            / max(1, sum(1 for r in ok if r["run"] == n))
            for n in sorted({r["run"] for r in ok})
        ]
        ok_low = [r for r in ok if r["id"] in low]
        triples = [(r["answer"], r["probability"], labels[r["id"]]) for r in ok]
        triples_low = [(r["answer"], r["probability"], labels[r["id"]]) for r in ok_low]
        lines.append(
            "| "
            + " | ".join(
                [
                    engine,
                    f"{len(ok)}/{len(mine) - len(ok)}",
                    _pct(sum(right) / len(ok)) if ok else "–",
                    f"{_pct(min(per_run))}–{_pct(max(per_run))}" if per_run else "–",
                    f"{brier(triples, positive=positive):.3f}" if ok else "–",
                    _pct(sum(a == lab for a, _, lab in triples_low) / len(ok_low))
                    if ok_low
                    else "–",
                    f"{brier(triples_low, positive=positive):.3f}" if ok_low else "–",
                    f"${sum(r['cost_usd'] for r in ok) / len(ok):.6f}" if ok else "–",
                    f"{percentile([r['latency_ms'] for r in ok], 0.5):.0f} ms" if ok else "–",
                    f"{percentile([r['latency_ms'] for r in ok], 0.95):.0f} ms" if ok else "–",
                ]
            )
            + " |"
        )
        cut = threshold([(r["probability"], r["answer"] == labels[r["id"]]) for r in ok])
        cuts.append(
            f"| {engine} | {cut[0]:.3f} | {cut[1]}/{len(ok)} ({_pct(cut[1] / len(ok))}) |"
            f" {_pct(cut[2] / cut[1])} |"
            if cut
            else f"| {engine} | none reaches {_pct(TARGET)} | 0/{len(ok)} | – |"
        )

    lines += [
        "",
        f"## Threshold: the lowest probability at which routed items are at least {_pct(TARGET)} right",
        "",
        "| Engine | Threshold | Routed without a person | Right among routed |",
        "|---|---|---|---|",
        *cuts,
        "",
        "The stage applies its threshold to the primary engine's probability; an answer from"
        " the fallback always goes to a person.",
        "",
        "## Self-consistency (SPEC §6)",
        "",
    ]
    if not relabels:
        lines.append("no relabel file: the set has not been relabelled yet.")
    else:
        by_id = {r["id"]: r for r in rows}
        n = len(relabels)
        for column in ("work_item_type", "security"):
            k = sum(p[column] == by_id[p["id"]][column] for p in relabels)
            lo, hi = wilson(k, n)
            name = "type" if column == "work_item_type" else column
            lines.append(f"- {name} {k}/{n} (95% CI {_pct(lo)}–{_pct(hi)})")
    return "\n".join(lines) + "\n"
