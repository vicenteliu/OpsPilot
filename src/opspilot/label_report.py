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
from .judgment import JudgmentEngine, Question, p_yes_of
from .kb.pages import page_state
from .label_set import LABEL_SET_DIR, LabelSetError, _read_jsonl
from .orchestrator.ticket_summary import _format_ticket
from .redaction import Redactor

RUNS_PATH: Final = LABEL_SET_DIR / "runs_v1.jsonl"
RUNS: Final = 3
TARGET: Final = 0.95  # routed without a person, at least this right (ADR-0040)

Show = Callable[[str], None]


def runs_path(question: Question) -> Path:
    """Where a decision's calls are kept: d2's in its first file, each other by its version.

    Kept apart because both decisions' Playbook-model engines share a name, and
    a call answered against one answer space says nothing about another.
    """
    if question.id == "d2":
        return RUNS_PATH
    return LABEL_SET_DIR / f"runs_{question.version.replace('-', '_')}.jsonl"


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


# The label column each decision is measured against (SPEC §1).
_COLUMN: Final = {
    "d1": "security",
    "d3": "same",
    "d2": "work_item_type",
    "d4": "enough",
    "d6": "team",
    "d7": "impact",
    "d8": "urgency",
    "d9": "known_fix",
    "r1": "catalog_item",
    "r2": "really",
    "r3": "enough_to_fulfil",
}


def _check_set(rows: list[dict[str, Any]], question: Question) -> None:
    column = _COLUMN.get(question.id, "work_item_type")
    if any(r.get(column) is None for r in rows):
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
    candidates: dict[str, list[dict[str, Any]]] | None = None,
    ask_with: Callable[[dict[str, Any]], Question] | None = None,
) -> int:
    """Ask every engine every row, ``runs`` times; return how many calls this made.

    With ``candidates`` (decision 9), each row is asked once per candidate
    page, shown the Work item and the page as the labeller saw it, and each
    record names its ``page``. With ``ask_with`` (decision 3), each row is
    asked the question it builds, e.g. over the row's own open Work items.
    """
    _check_set(rows, question)
    items: list[tuple[dict[str, Any], str | None, str]] = []
    for row in rows:
        state = row_state(row, redactor)
        if candidates is None:
            items.append((row, None, state))
            continue
        if row["id"] not in candidates:
            raise LabelSetError(f"{row['id']} has no candidate pages; the set and them differ")
        for candidate in candidates[row["id"]]:
            items.append((row, candidate["source_path"], page_state(state, candidate)))
    done = (
        {
            (r["engine"], r["run"], r["id"], r.get("page"))
            for r in _read_jsonl(out)
            if r["error"] is None
        }
        if out.is_file()
        else set()
    )
    made = 0
    for engine in engines:
        for n in range(1, runs + 1):
            failed = 0
            for row, page, state in items:
                if (engine.name, n, row["id"], page) in done:
                    continue
                record: dict[str, Any] = {"engine": engine.name, "run": n, "id": row["id"]}
                if page is not None:
                    record["page"] = page
                started = time.monotonic()
                try:
                    asked = ask_with(row) if ask_with is not None else question
                    j = engine.judge(asked, state, timeout_s=timeout_s)
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


def with_whole_pages(
    candidates: dict[str, list[dict[str, Any]]], source: Path, redactor: Redactor
) -> dict[str, list[dict[str, Any]]]:
    """The candidates with each one's whole page, redacted, in place of its passage (#226).

    The pages are read from ``source``, the handbook checkout the KB was built
    from, and keyed by their path in it as the KB keys them.
    """
    pages: dict[str, str] = {}
    out: dict[str, list[dict[str, Any]]] = {}
    for row_id, offered in candidates.items():
        for c in offered:
            page = c["source_path"]
            if page not in pages:
                path = source / page
                if not path.is_file():
                    raise LabelSetError(f"{page} is not in {source}; is it the KB's handbook?")
                pages[page] = redactor.redact(path.read_text(encoding="utf-8")).text
        out[row_id] = [c | {"excerpt": pages[c["source_path"]]} for c in offered]
    return out


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


def recall_cut(judged: list[tuple[float, bool]]) -> float | None:
    """Decision 1's cut: the highest P(yes) at which every labelled security item stops.

    That is the lowest P(yes) any of them got (ADR-0040): a wrong "not
    security" is the one mistake the next step cannot undo, and the false
    alarms are the price. None when nothing is labelled a security item.
    """
    yes = [p for p, labelled_yes in judged if labelled_yes]
    return min(yes) if yes else None


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


def _first_pass(
    rows: list[dict[str, Any]], reviews: list[dict[str, Any]] | None
) -> dict[str, dict[str, Any]]:
    """The rows as first labelled, against d1-v1: before d1-v2's relabel and the review."""
    first = {r["id"]: {**r, "security": r.get("security_d1_v1", r["security"])} for r in rows}
    for e in reviews or []:
        first[e["id"]]["security"] = e["before"]
    return first


def report_markdown(
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    relabels: list[dict[str, Any]] | None,
    question: Question,
    reviews: list[dict[str, Any]] | None = None,
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
        # Against the first pass: a security label the review changed is read
        # as it stood before the review, so the agreement keeps its meaning.
        first = _first_pass(rows, reviews)
        n = len(relabels)
        for column in ("work_item_type", "security"):
            k = sum(p[column] == first[p["id"]][column] for p in relabels)
            lo, hi = wilson(k, n)
            name = "type" if column == "work_item_type" else column
            lines.append(f"- {name} {k}/{n} (95% CI {_pct(lo)}–{_pct(hi)})")
    if reviews:
        changed = sum(e["after"] != e["before"] for e in reviews)
        lines += [
            "",
            "## Security review (SPEC §6)",
            "",
            f"After labelling, the {len(reviews)} rows whose `security` label and the drafter's"
            f" split were reviewed again against d1; {changed} changed. The review was not blind:"
            " the reviewer saw the label they had given.",
        ]
    return "\n".join(lines) + "\n"


def security_report_markdown(
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    question: Question,
    reviews: list[dict[str, Any]] | None,
    relabels: list[dict[str, Any]] | None = None,
) -> str:
    """Decision 1 on the label set: each engine's cut, its recall and its false alarms."""
    labels = {r["id"]: r["security"] for r in rows}
    if stray := sorted({r["id"] for r in records} - labels.keys()):
        raise LabelSetError(f"the runs file answers rows the set does not have: {', '.join(stray)}")
    engines = list(dict.fromkeys(r["engine"] for r in records))
    runs = max((r["run"] for r in records), default=0)
    labelled_yes = sum(v == "yes" for v in labels.values())
    lines = [
        f"# {question.version} on the label set: the engines compared",
        "",
        f"{len(rows)} rows is not a benchmark: synthetic, English, labelled by one person, and the"
        " threshold is set on the same rows it is reported on; there is no held-out split at this"
        f" size. Each engine answered every row {runs} times; the figures pool the runs."
        f" {labelled_yes} of {len(rows)} rows are labelled `security: yes`.",
    ]
    if reviews:
        changed = sum(e["after"] != e["before"] for e in reviews)
        lines[-1] += (
            f" Those labels were reviewed after labelling where they and the drafter split:"
            f" {changed} of {len(reviews)} reviewed labels changed, and the review was not blind."
        )
    lines += [
        "",
        "| Engine | Calls ok/failed | Accuracy at 0.5 | Brier on P(yes) | Cost/call | p50 | p95 |",
        "|---|---|---|---|---|---|---|",
    ]
    cuts: list[str] = []
    for engine in engines:
        mine = [r for r in records if r["engine"] == engine]
        ok = [r for r in mine if r["error"] is None]
        if not ok:
            lines.append(f"| {engine} | 0/{len(mine)} | – | – | – | – | – |")
            cuts.append(f"| {engine} | – | – | – | – |")
            continue
        triples = [(r["answer"], r["probability"], labels[r["id"]]) for r in ok]
        latencies = [r["latency_ms"] for r in ok]
        lines.append(
            f"| {engine} | {len(ok)}/{len(mine) - len(ok)}"
            f" | {_pct(sum(a == lab for a, _, lab in triples) / len(ok))}"
            f" | {brier(triples, positive='yes'):.3f}"
            f" | ${sum(r['cost_usd'] for r in ok) / len(ok):.6f}"
            f" | {percentile(latencies, 0.5):.0f} ms | {percentile(latencies, 0.95):.0f} ms |"
        )
        judged = [(p_yes_of(r["answer"], r["probability"]), labels[r["id"]] == "yes") for r in ok]
        cut = recall_cut(judged)
        if cut is None:
            cuts.append(f"| {engine} | no labelled security item | – | – | – |")
            continue
        yes = [p for p, y in judged if y]
        no = [p for p, y in judged if not y]
        stopped = sum(p >= cut for p, _ in judged)
        alarms = sum(p >= cut for p in no)
        cuts.append(
            f"| {engine} | {cut:.3f}"
            f" | {sum(p >= cut for p in yes)}/{len(yes)} ({_pct(sum(p >= cut for p in yes) / len(yes))})"
            f" | {stopped}/{len(judged)} ({_pct(stopped / len(judged))})"
            f" | {alarms}/{len(no)} ({_pct(alarms / len(no)) if no else '–'}) |"
        )
    lines += [
        "",
        "## Threshold: the highest P(yes) at which every labelled security item reaches a person",
        "",
        "| Engine | Threshold | Recall | Stopped | False alarms among the labelled no |",
        "|---|---|---|---|---|",
        *cuts,
        "",
        "The stage stops a Work item at or above its primary engine's threshold on P(yes); an"
        " answer from the fallback always stops.",
    ]
    if relabels:
        # The column this decision is measured on, read against the first pass.
        first = _first_pass(rows, reviews)
        k = sum(p["security"] == first[p["id"]]["security"] for p in relabels)
        lo, hi = wilson(k, len(relabels))
        lines += [
            "",
            "## Self-consistency (SPEC §6)",
            "",
            f"- security {k}/{len(relabels)} (95% CI {_pct(lo)}–{_pct(hi)})",
        ]
    return "\n".join(lines) + "\n"


def _ordering_lines(
    known: dict[str, set[str]],
    records: list[dict[str, Any]],
    engines: list[str],
    candidates: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """Each engine's order of a row's pages against retrieval's own (#286).

    The person reads the pages in an order: is a fix first, or in the first
    two? Retrieval's order is the candidates' as found; an engine's is by
    P(yes), retrieval's order breaking ties. Counted on the rows with a fix,
    per row for retrieval and per row and run for an engine.
    """
    fixable = [i for i, fixes in known.items() if fixes and i in candidates]

    def hits(order: list[str], fixes: set[str]) -> tuple[bool, bool]:
        return bool(order[:1] and order[0] in fixes), bool(set(order[:2]) & fixes)

    retrieval = [hits([c["source_path"] for c in candidates[i]], known[i]) for i in fixable]
    rows = (
        [
            f"| retrieval | {sum(a for a, _ in retrieval)}/{len(fixable)}"
            f" ({_pct(sum(a for a, _ in retrieval) / len(fixable))})"
            f" | {sum(b for _, b in retrieval)}/{len(fixable)}"
            f" ({_pct(sum(b for _, b in retrieval) / len(fixable))}) |"
        ]
        if fixable
        else []
    )
    for engine in engines:
        scored: dict[tuple[int, str], dict[str, float]] = {}
        for r in records:
            if r["engine"] == engine and r["error"] is None and r["id"] in fixable:
                p = p_yes_of(r["answer"], r["probability"])
                scored.setdefault((r["run"], r["id"]), {})[r["page"]] = p
        results = []
        for (_, i), p_by_page in scored.items():
            pages = [c["source_path"] for c in candidates[i]]
            if set(pages) - p_by_page.keys():
                continue  # a page went unanswered: no order to read
            order = sorted(pages, key=lambda page: -p_by_page[page])
            results.append(hits(order, known[i]))
        if results:
            first, two = sum(a for a, _ in results), sum(b for _, b in results)
            rows.append(
                f"| {engine} | {first}/{len(results)} ({_pct(first / len(results))})"
                f" | {two}/{len(results)} ({_pct(two / len(results))}) |"
            )
    return [
        "",
        "## Ordering: the pages a person reads first (#286)",
        "",
        "On the rows with a fix: whether the first page, or one of the first two, fixes it, in"
        " retrieval's order (per row) and in each engine's order by P(yes) (per row and run).",
        "",
        "| Order | First page a fix | A fix in the first two |",
        "|---|---|---|",
        *rows,
    ]


def known_fix_report_markdown(
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    question: Question,
    *,
    whole_page: bool = False,
    candidates: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    """Decision 9 on the label set: each row's likeliest page, and the cut that sends it.

    Per row and run, the candidate with the highest P(yes) is the one the stage
    would send; it is right when the labeller marked that page a known fix.
    The cut is the lowest P(yes) at which the fixes sent are at least 95% right,
    the rule decision 2's cut follows (ADR-0040).
    """
    known = {r["id"]: set(r["known_fix"]) for r in rows}
    if stray := sorted({r["id"] for r in records} - known.keys()):
        raise LabelSetError(f"the runs file answers rows the set does not have: {', '.join(stray)}")
    engines = list(dict.fromkeys(r["engine"] for r in records))
    runs = max((r["run"] for r in records), default=0)
    fixable = sum(bool(v) for v in known.values())
    lines = [
        f"# {question.version} on the label set: the engines compared",
        "",
        f"{len(rows)} rows is not a benchmark: synthetic, English, labelled by one person, and the"
        " threshold is set on the same rows it is reported on; there is no held-out split at this"
        f" size. Each engine answered every candidate page of every row {runs} times, shown"
        f" {'the whole page' if whole_page else 'the passage the labeller saw'}; the figures"
        f" pool the runs. {fixable} of {len(rows)} rows have a known fix among their candidates.",
        "",
        "| Engine | Calls ok/failed | Accuracy at 0.5, per page | Brier on P(yes) | Cost/call"
        " | p50 | p95 |",
        "|---|---|---|---|---|---|---|",
    ]
    cuts: list[str] = []
    for engine in engines:
        mine = [r for r in records if r["engine"] == engine]
        ok = [r for r in mine if r["error"] is None]
        if not ok:
            lines.append(f"| {engine} | 0/{len(mine)} | – | – | – | – | – |")
            cuts.append(f"| {engine} | – | – | – | – | – |")
            continue
        label = {True: "yes", False: "no"}
        triples = [(r["answer"], r["probability"], label[r["page"] in known[r["id"]]]) for r in ok]
        latencies = [r["latency_ms"] for r in ok]
        lines.append(
            f"| {engine} | {len(ok)}/{len(mine) - len(ok)}"
            f" | {_pct(sum(a == lab for a, _, lab in triples) / len(ok))}"
            f" | {brier(triples, positive='yes'):.3f}"
            f" | ${sum(r['cost_usd'] for r in ok) / len(ok):.6f}"
            f" | {percentile(latencies, 0.5):.0f} ms | {percentile(latencies, 0.95):.0f} ms |"
        )
        # A row and run the engine did not see every page of has no likeliest page.
        answered = {(r["run"], r["id"], r["page"]) for r in ok}
        unseen = {
            (r["run"], r["id"])
            for r in mine
            if r["error"] is not None and (r["run"], r["id"], r["page"]) not in answered
        }
        best: dict[tuple[int, str], tuple[float, str]] = {}
        for r in ok:
            p = p_yes_of(r["answer"], r["probability"])
            key = (r["run"], r["id"])
            if key in unseen:
                continue
            if key not in best or p > best[key][0]:
                best[key] = (p, r["page"])
        decisions = [(p, page in known[i], bool(known[i])) for (_, i), (p, page) in best.items()]
        cut = threshold([(p, right) for p, right, _ in decisions])
        if cut is None:
            cuts.append(f"| {engine} | none reaches {_pct(TARGET)} | – | – | – | – |")
            continue
        sent = [(right, has_fix) for p, right, has_fix in decisions if p >= cut[0]]
        has = sum(has_fix for _, _, has_fix in decisions)
        none = len(decisions) - has
        given_right = sum(right for right, _ in sent)
        wrongly_sent = sum(not has_fix for _, has_fix in sent)
        cuts.append(
            f"| {engine} | {cut[0]:.3f}"
            f" | {len(sent)}/{len(decisions)} ({_pct(len(sent) / len(decisions))})"
            f" | {given_right}/{len(sent)} ({_pct(given_right / len(sent))})"
            f" | {given_right}/{has} ({_pct(given_right / has) if has else '–'})"
            f" | {wrongly_sent}/{none} ({_pct(wrongly_sent / none) if none else '–'}) |"
        )
    lines += [
        "",
        f"## Threshold: the lowest P(yes) at which the fixes sent are at least {_pct(TARGET)} right",
        "",
        "Per row and run, the candidate with the highest P(yes) is the fix the stage would send,"
        " and each count below is of rows and runs: a row counts once per run. A row and run with"
        " a page no call answered is left out.",
        "",
        "| Engine | Threshold | Fixes sent | Right among sent | Rows with a fix, given a right page"
        " | Rows with none, sent a page |",
        "|---|---|---|---|---|---|",
        *cuts,
    ]
    if candidates is not None:
        lines += _ordering_lines(known, records, engines, candidates)
    return "\n".join(lines) + "\n"


def incident_report_markdown(
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    question: Question,
    *,
    rows_are: str = "Incidents",
    idle: str | None = None,
) -> str:
    """A decision asked of one type's rows (decisions 4, 6, 7, 8; r1 of requests): each
    engine's answer against the label. ``rows_are`` names them in the report;
    ``idle`` is the answer that, like one below the cut, changes nothing (r1's
    `none`, r2's `request`), so the report also gives the cut on the others.

    The report gives what always answering the most common label would score:
    with few rows at some answers, that is the bar an engine has to clear. A
    Score's levels are ordered (#227), so for one it also gives how often an
    answer is within one level of the label; a Choice's answers are not (#228).
    The cut is decision 2's rule: the lowest probability at which the answers
    decided without a person are at least 95% right (ADR-0040).
    """
    column = _COLUMN[question.id]
    if any(r.get(column) is None for r in rows):
        raise LabelSetError(f"label every Incident's {column} first; the report reads them all")
    labels = {r["id"]: r[column] for r in rows}
    if stray := sorted({r["id"] for r in records} - labels.keys()):
        raise LabelSetError(f"the runs file answers rows the set does not have: {', '.join(stray)}")
    levels = list(question.answers)
    rank = {level: n for n, level in enumerate(levels)}
    ordered = question.kind == "score"
    # Past a few answers a column per answer is unreadable (a catalog, #231):
    # each labelled answer gets right, `none`, or another instead.
    wide = len(levels) > 4
    labelled = {level: sum(v == level for v in labels.values()) for level in levels}
    common = max(levels, key=labelled.__getitem__)
    engines = list(dict.fromkeys(r["engine"] for r in records))
    runs = max((r["run"] for r in records), default=0)
    lines = [
        f"# {question.version} on the label set's {rows_are}: the engines compared",
        "",
        f"{len(rows)} {rows_are} is not a benchmark: synthetic, English, labelled by one person, and"
        " the threshold is set on the same rows it is reported on; there is no held-out split at"
        f" this size. Each engine answered every one {runs} times; the figures pool the runs.",
        "",
        "Labelled: "
        + ", ".join(f"{level} {n}" for level, n in labelled.items())
        + f". Always answering {common} would be {_pct(labelled[common] / len(rows))} right.",
        "",
        "| Engine | Calls ok/failed | Accuracy"
        + (" | Within one level" if ordered else "")
        + " | Brier on the answer | Cost/call | p50 | p95 |",
        "|---|---|---|---|---|---|---|" + ("---|" if ordered else ""),
    ]
    answered: list[str] = []
    cuts: list[str] = []
    asks: list[str] = []
    named: list[str] = []
    for engine in engines:
        mine = [r for r in records if r["engine"] == engine]
        ok = [r for r in mine if r["error"] is None]
        if not ok:
            lines.append(f"| {engine} | 0/{len(mine)} |" + " – |" * (6 if ordered else 5))
            cuts.append(f"| {engine} | – | 0/0 | – |")
            continue
        judged = [(r["probability"], r["answer"] == labels[r["id"]]) for r in ok]
        right = sum(hit for _, hit in judged)
        near = sum(abs(rank[r["answer"]] - rank[labels[r["id"]]]) <= 1 for r in ok)
        latencies = [r["latency_ms"] for r in ok]
        lines.append(
            f"| {engine} | {len(ok)}/{len(mine) - len(ok)} | {_pct(right / len(ok))}"
            + (f" | {_pct(near / len(ok))}" if ordered else "")
            + f" | {sum((p - hit) ** 2 for p, hit in judged) / len(ok):.3f}"
            f" | ${sum(r['cost_usd'] for r in ok) / len(ok):.6f}"
            f" | {percentile(latencies, 0.5):.0f} ms | {percentile(latencies, 0.95):.0f} ms |"
        )
        for level in levels:
            if not labelled[level]:
                continue
            said = [r["answer"] for r in ok if labels[r["id"]] == level]
            if wide:
                nones = said.count("none") if level != "none" else 0
                answered.append(
                    f"| {engine} | {level} ({len(said)}) | {said.count(level)}"
                    f" | {nones if level != 'none' else '–'} | {len(said) - said.count(level) - nones} |"
                )
            else:
                answered.append(
                    f"| {engine} | {level} ({len(said)})"
                    + "".join(f" | {said.count(a)}" for a in levels)
                    + " |"
                )
        cut = threshold(judged)
        cuts.append(
            f"| {engine} | {cut[0]:.3f} | {cut[1]}/{len(ok)} ({_pct(cut[1] / len(ok))}) |"
            f" {_pct(cut[2] / cut[1])} |"
            if cut
            else f"| {engine} | none reaches {_pct(TARGET)} | 0/{len(ok)} | – |"
        )
        if question.kind == "noul":
            asks.append(_asks_row(engine, ok, labels))
        elif idle is not None or "none" in question.answers:
            named.append(_named_row(engine, ok, labels, idle or "none"))
    lines += [
        "",
        "## What each engine answered, by label",
        "",
        (
            "| Engine | Labelled (answers) | Right | Said none | Another |"
            if wide
            else "| Engine | Labelled (answers) | " + " | ".join(levels) + " |"
        ),
        "|---|---|" + "---|" * (3 if wide else len(levels)),
        *answered,
        "",
        f"## Threshold: the lowest probability at which the answers decided are at least"
        f" {_pct(TARGET)} right",
        "",
        "| Engine | Threshold | Decided without a person | Right among them |",
        "|---|---|---|---|",
        *cuts,
        "",
        "The stage applies its threshold to the primary engine's probability; an answer from"
        " the fallback always goes to a person.",
    ]
    if named:
        lines += [
            "",
            f"## Named: the lowest probability at which the answers other than `{idle or 'none'}`"
            f" are at least {_pct(TARGET)} right",
            "",
            f"`{idle or 'none'}`, and an answer below the cut, take the same way, so only another"
            " answer acts; this is its cut (#231, #293).",
            "",
            "| Engine | Threshold | Named | Right among them | Labelled named, named rightly"
            f" | Labelled {idle or 'none'}, named |",
            "|---|---|---|---|---|---|",
            *named,
        ]
    if asks:
        lines += [
            "",
            f"## Asks: the lowest P(no) at which the Work items asked about are at least"
            f" {_pct(TARGET)} labelled no",
            "",
            "Only a `no` that clears its cut acts: the run waits and the reporter is asked"
            " (decision 4, #229; r3, #294). A `yes`, or a `no` below the cut, goes on as before.",
            "",
            "| Engine | Threshold | Asked | Right among them | Labelled no, asked"
            " | Labelled yes, asked |",
            "|---|---|---|---|---|---|",
            *asks,
        ]
    return "\n".join(lines) + "\n"


def _named_row(
    engine: str, ok: list[dict[str, Any]], labels: dict[str, str], idle: str = "none"
) -> str:
    """One engine's answers other than ``idle`` at the lowest cut that keeps them 95% right."""
    labelled_none = sum(labels[r["id"]] == idle for r in ok)
    labelled_named = len(ok) - labelled_none
    answers = [
        (r["probability"], r["answer"] == labels[r["id"]], r) for r in ok if r["answer"] != idle
    ]
    cut = threshold([(p, hit) for p, hit, _ in answers])
    if cut is None:
        return (
            f"| {engine} | none reaches {_pct(TARGET)} | 0/{len(ok)} | – | 0/{labelled_named} | – |"
        )
    sent = [(hit, r) for p, hit, r in answers if p >= cut[0]]
    hits = sum(hit for hit, _ in sent)
    false = sum(labels[r["id"]] == idle for _, r in sent)
    return (
        f"| {engine} | {cut[0]:.3f} | {len(sent)}/{len(ok)} | {_pct(hits / len(sent))}"
        f" | {hits}/{labelled_named} | {false}/{labelled_none} |"
    )


def _asks_row(engine: str, ok: list[dict[str, Any]], labels: dict[str, str]) -> str:
    """One engine's asks at the lowest cut on its `no` answers that keeps them 95% right."""
    labelled_no = sum(labels[r["id"]] == "no" for r in ok)
    labelled_yes = len(ok) - labelled_no
    nos = [(r["probability"], labels[r["id"]] == "no") for r in ok if r["answer"] == "no"]
    if not nos:
        return f"| {engine} | never answered no | 0/{len(ok)} | – | 0/{labelled_no} | 0/{labelled_yes} |"
    cut = threshold(nos)
    if cut is None:
        return (
            f"| {engine} | none reaches {_pct(TARGET)} | 0/{len(ok)} | – | 0/{labelled_no}"
            f" | 0/{labelled_yes} |"
        )
    sent = [hit for p, hit in nos if p >= cut[0]]
    hits = sum(sent)
    return (
        f"| {engine} | {cut[0]:.3f} | {len(sent)}/{len(ok)} | {_pct(hits / len(sent))}"
        f" | {hits}/{labelled_no} | {len(sent) - hits}/{labelled_yes} |"
    )


def already_open_report_markdown(
    items: list[dict[str, Any]], records: list[dict[str, Any]], question: Question
) -> str:
    """Decision 3 on its items: the open Work item each engine names, against the label (#230).

    The stage acts only on a match: one that clears its cut is named in the
    write-back comment. So beside accuracy the report gives that cut, the
    lowest probability at which the matches named are at least 95% right, with
    how many labelled matches it names rightly and how many items labelled
    `none` it names a match for.
    """
    labels = {i["id"]: i["same"] for i in items}
    if any(v is None for v in labels.values()):
        raise LabelSetError("label every item first; the report reads them all")
    if stray := sorted({r["id"] for r in records} - labels.keys()):
        raise LabelSetError(
            f"the runs file answers items the set does not have: {', '.join(stray)}"
        )
    matches = sum(v != "none" for v in labels.values())
    engines = list(dict.fromkeys(r["engine"] for r in records))
    runs = max((r["run"] for r in records), default=0)
    lines = [
        f"# {question.version} on its items: the engines compared",
        "",
        f"{len(items)} items is not a benchmark: synthetic, English, labelled by one person, and"
        " the threshold is set on the same items it is reported on. Each engine answered every"
        f" item {runs} times; the figures pool the runs. {matches} items repeat one of their five"
        " open Work items, the duplicates drafted for this (SPEC §5); the rest repeat none.",
        "",
        "| Engine | Calls ok/failed | Accuracy | Brier on the answer | Cost/call | p50 | p95 |",
        "|---|---|---|---|---|---|---|",
    ]
    answered: list[str] = []
    cuts: list[str] = []
    for engine in engines:
        mine = [r for r in records if r["engine"] == engine]
        ok = [r for r in mine if r["error"] is None]
        if not ok:
            lines.append(f"| {engine} | 0/{len(mine)} | – | – | – | – | – |")
            cuts.append(f"| {engine} | – | 0/0 | – | – | – |")
            continue
        judged = [(r["probability"], r["answer"] == labels[r["id"]]) for r in ok]
        latencies = [r["latency_ms"] for r in ok]
        lines.append(
            f"| {engine} | {len(ok)}/{len(mine) - len(ok)}"
            f" | {_pct(sum(hit for _, hit in judged) / len(ok))}"
            f" | {sum((p - hit) ** 2 for p, hit in judged) / len(ok):.3f}"
            f" | ${sum(r['cost_usd'] for r in ok) / len(ok):.6f}"
            f" | {percentile(latencies, 0.5):.0f} ms | {percentile(latencies, 0.95):.0f} ms |"
        )
        on_match = [r for r in ok if labels[r["id"]] != "none"]
        on_none = [r for r in ok if labels[r["id"]] == "none"]
        answered.append(
            f"| {engine} | a match ({len(on_match)})"
            f" | {sum(r['answer'] == labels[r['id']] for r in on_match)}"
            f" | {sum(r['answer'] == 'none' for r in on_match)}"
            f" | {sum(r['answer'] not in ('none', labels[r['id']]) for r in on_match)} |"
        )
        answered.append(
            f"| {engine} | none ({len(on_none)}) | – | {sum(r['answer'] == 'none' for r in on_none)}"
            f" | {sum(r['answer'] != 'none' for r in on_none)} |"
        )
        named = [
            (r["probability"], r["answer"] == labels[r["id"]], r)
            for r in ok
            if r["answer"] != "none"
        ]
        cut = threshold([(p, hit) for p, hit, _ in named])
        if cut is None:
            cuts.append(f"| {engine} | none reaches {_pct(TARGET)} | 0/{len(ok)} | – | – | – |")
            continue
        sent = [(hit, r) for p, hit, r in named if p >= cut[0]]
        right = sum(hit for hit, _ in sent)
        false = sum(labels[r["id"]] == "none" for _, r in sent)
        cuts.append(
            f"| {engine} | {cut[0]:.3f} | {len(sent)}/{len(ok)} | {_pct(right / len(sent))}"
            f" | {right}/{len(on_match)} | {false}/{len(on_none)} |"
        )
    lines += [
        "",
        "## What each engine answered, by label",
        "",
        "| Engine | Labelled | Named the match | Said none | Named another |",
        "|---|---|---|---|---|",
        *answered,
        "",
        f"## Threshold: the lowest probability at which the matches named are at least"
        f" {_pct(TARGET)} right",
        "",
        "A match that clears it is named in the comment, for a person to link; anything else"
        " says nothing.",
        "",
        "| Engine | Threshold | Matches named | Right among them | Labelled matches, named"
        " | Labelled none, named a match |",
        "|---|---|---|---|---|---|",
        *cuts,
    ]
    return "\n".join(lines) + "\n"
