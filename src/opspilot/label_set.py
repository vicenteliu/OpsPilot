"""Draft the synthetic label set the first Judgments slice is measured on (#224).

``judgments/label_set/SPEC.md`` says what the set contains; this module drafts
it. The script sets the mix, not the model: 80 slots, each with an intent, a
security flag, a topic and a form, dealt into 8 batches of 10. A model through
OpenRouter writes one Work item per slot, and a row is kept only when it keeps
to its slot: the attributes it echoes, its form's length, the channel a
forwarded email needs, the domains it names, and the Redactor, which must leave
it unchanged (SPEC §4) so that every engine later sees what the labeller saw.

Two steps, per SPEC §8. ``run_trial`` drafts batch 1 with one candidate model
and says how many rows kept to their slot; it is run once per candidate.
``run_draft`` keeps the winner's trial as batch 1, drafts the other slots with
the same model, redrafts any row that failed or nearly repeats another on its
topic, shuffles, assigns ids, and writes the set with every label left empty.

Every call's charge, as OpenRouter reports it, is appended to a ledger, and no
call starts once the ledger reaches the cap (SPEC §5). A check made *before*
each call can overshoot by at most one call.

``label_rows`` and ``relabel_rows`` are the person's half (SPEC §6): a blind
pass over the set that shows a row's subject, body and channel and nothing
else, and a blind relabel of 10 random rows a day later for self-consistency.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Final

from .errors import OpsPilotError
from .judgment import Question
from .orchestrator.ticket_summary import _parse_summary_json
from .providers.base import ProviderProtocol
from .providers.types import Message, SamplingParams
from .redaction import Redactor

LABEL_SET_DIR: Final = Path("judgments/label_set")
DRAFT_PROMPT_PATH: Final = LABEL_SET_DIR / "DRAFT_PROMPT.md"
OUT_PATH: Final = LABEL_SET_DIR / "label_set_v1.jsonl"
BUDGET_USD: Final = 1.0
SEED: Final = 224
MAX_ROUNDS: Final = 4  # the first pass plus three redraft rounds

INTENTS: Final[dict[str, int]] = {"incident": 36, "service_request": 28, "ambiguous": 16}
# At least 12 security rows, spread across all three intents (SPEC §3).
SECURITY_BY_INTENT: Final[dict[str, int]] = {"incident": 5, "service_request": 3, "ambiguous": 4}
TOPICS: Final[tuple[str, ...]] = (
    "VPN and remote access",
    "identity and access (accounts, MFA, SSO)",
    "endpoint management (enrolment, policies, patching)",
    "endpoint encryption and keys",
    "provisioning (new machine, reimage)",
    "Microsoft 365",
    "other SaaS admin",
    "web and TLS (expired certificates, internal sites)",
    "site network (Wi-Fi, DNS, printers on the network)",
    "ITSM and assets (hardware requests, returns, loaners)",
    "working with security",
)
MAX_PER_TOPIC: Final = 8
FORMS: Final[dict[str, int]] = {  # the remaining rows are "ordinary"
    "one_liner": 10,
    "long_rambling": 8,
    "non_native": 6,
    "pasted_error": 6,
    "forwarded_email": 4,
    "two_issues": 3,
}
CHANNELS: Final = ("email", "portal", "chat")
BATCHES: Final = 8
BATCH_SIZE: Final = 10
TOTAL: Final = BATCHES * BATCH_SIZE

_DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|co|uk|de|cn|info|biz|edu|gov|app|dev|ai|cloud)\b",
    re.IGNORECASE,
)
_ALLOWED_DOMAIN_RE = re.compile(r"(?:^|\.)example\.(?:com|org)$", re.IGNORECASE)
_NEAR_DUPLICATE = 0.85


class LabelSetError(OpsPilotError):
    """The label set cannot be drafted as asked."""


@dataclass(frozen=True)
class Slot:
    """One row the script asks for: what the drafter must write, not what it is."""

    slot: str  # S01..S80
    batch: int  # 1..8
    intent: str
    security: str  # yes | no
    topic: str
    form: str


def plan_slots(seed: int = SEED) -> list[Slot]:
    """The 80 slots, dealt so each batch carries its share of every quota."""
    rng = random.Random(seed)
    intents = [intent for intent, n in INTENTS.items() for _ in range(n)]
    security = [
        flag
        for intent, n in INTENTS.items()
        for flag in ["yes"] * SECURITY_BY_INTENT[intent] + ["no"] * (n - SECURITY_BY_INTENT[intent])
    ]
    topics = [TOPICS[i % len(TOPICS)] for i in range(TOTAL)]
    forms = [form for form, n in FORMS.items() for _ in range(n)]
    forms += ["ordinary"] * (TOTAL - len(forms))
    rng.shuffle(topics)
    rng.shuffle(forms)
    rows = sorted(
        zip(intents, security, topics, forms, strict=True), key=lambda r: (r[0], r[1], r[3])
    )
    slots: list[Slot] = []
    for b in range(BATCHES):
        batch = rows[b::BATCHES]
        rng.shuffle(batch)
        for i, (intent, flag, topic, form) in enumerate(batch):
            n = b * BATCH_SIZE + i + 1
            slots.append(Slot(f"S{n:02d}", b + 1, intent, flag, topic, form))
    return slots


def check_row(row: dict[str, Any], slot: Slot, redactor: Redactor) -> list[str]:
    """What keeps this row from its slot; empty when it may be kept."""
    problems = [
        f"{key} is {row.get(key)!r}, the slot says {want!r}"
        for key, want in (
            ("topic", slot.topic),
            ("draft_intent", slot.intent),
            ("draft_security", slot.security),
        )
        if row.get(key) != want
    ]
    subject, body, channel = row.get("subject"), row.get("body"), row.get("channel")
    if not isinstance(subject, str) or not isinstance(body, str):
        return [*problems, "subject and body must be strings"]
    problems += _text_problems(subject, body, channel, redactor)
    words = len(body.split())
    if slot.form == "one_liner" and words >= 12:
        problems.append(f"a one-liner's body is {words} words, not under 12")
    if slot.form == "long_rambling" and not 100 <= words <= 150:
        problems.append(f"a long item's body is {words} words, not 100 to 150")
    if slot.form == "forwarded_email" and channel != "email":
        problems.append(f"a forwarded email came in by {channel!r}")
    return problems


def _text_problems(subject: str, body: str, channel: Any, redactor: Redactor) -> list[str]:
    """What keeps a drafted Work item's text out of the set, whatever its slot."""
    problems = []
    if not (subject.strip() or body.strip()):
        problems.append("the item is empty")
    if channel not in CHANNELS:
        problems.append(f"channel {channel!r} is not one of {', '.join(CHANNELS)}")
    words = len(body.split())
    if words > 150:
        problems.append(f"the body is {words} words, over 150")
    text = f"{subject}\n{body}"
    foreign = sorted(
        {m.group(0) for m in _DOMAIN_RE.finditer(text) if not _ALLOWED_DOMAIN_RE.search(m.group(0))}
    )
    if foreign:
        problems.append(f"names domains outside example.com/.org: {', '.join(foreign)}")
    redacted = redactor.redact(text)
    if redacted.hit_count:
        problems.append(f"the redactor would change it: {', '.join(sorted(redacted.types_seen()))}")
    return problems


def near_duplicates(rows: list[dict[str, Any]]) -> set[str]:
    """Slots whose item nearly repeats an earlier one on the same topic (SPEC §5)."""
    seen: dict[str, list[str]] = {}
    dups: set[str] = set()
    for row in rows:
        key = " ".join((row["subject"] or row["body"][:80]).lower().split())
        earlier = seen.setdefault(row["topic"], [])
        if any(SequenceMatcher(None, key, other).ratio() >= _NEAR_DUPLICATE for other in earlier):
            dups.add(row["slot"])
        else:
            earlier.append(key)
    return dups


@dataclass(frozen=True)
class BatchOutcome:
    kept: dict[str, dict[str, Any]]  # slot → row
    failed: dict[str, list[str]]  # slot → what was wrong
    cost_usd: float
    seconds: float


def _slot_message(slots: list[Slot], avoid: list[str]) -> str:
    table = [
        {
            "slot": s.slot,
            "intent": s.intent,
            "security": s.security,
            "topic": s.topic,
            "form": s.form,
        }
        for s in slots
    ]
    parts = [
        f"Write {len(slots)} Work items, one per slot:",
        "```json",
        json.dumps(table, indent=1),
        "```",
    ]
    if avoid:
        parts += ["", "Subjects already written on these topics; write something different:"]
        parts += [f"- {subject}" for subject in avoid]
    return "\n".join(parts)


def _spent(ledger: Path) -> float:
    if not ledger.is_file():
        return 0.0
    lines = ledger.read_text(encoding="utf-8").splitlines()
    return sum(float(json.loads(line)["cost_usd"]) for line in lines if line.strip())


def _draft(
    provider: ProviderProtocol,
    model: str,
    slots: list[Slot],
    *,
    system_prompt: str,
    redactor: Redactor,
    avoid: list[str],
    ledger: Path,
    budget_usd: float,
    phase: str,
) -> BatchOutcome:
    """One call for up to one batch of slots, checked row by row."""
    spent = _spent(ledger)
    if spent >= budget_usd:
        raise LabelSetError(
            f"budget reached: ${spent:.4f} of ${budget_usd:.2f} spent; no call made"
        )
    started = time.monotonic()
    resp = provider.chat(
        [
            Message(role="system", content=system_prompt),
            Message(role="user", content=_slot_message(slots, avoid)),
        ],
        model=model,
        params=SamplingParams(temperature=0.9, max_tokens=12_000),
        timeout_ms=300_000,
    )
    seconds = time.monotonic() - started
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": model,
            "phase": phase,
            "slots": len(slots),
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cost_usd": resp.usage.cost_usd,
            "seconds": round(seconds, 2),
        }
        f.write(json.dumps(entry) + "\n")

    parsed, err = _parse_summary_json(resp.content)
    if resp.finish_reason == "length":
        err = "the response was cut off at max_tokens"
    rows = parsed.get("rows") if err is None else None
    if not isinstance(rows, list):
        reason = err or "the response has no 'rows' list"
        return BatchOutcome({}, {s.slot: [reason] for s in slots}, resp.usage.cost_usd, seconds)

    by_slot = {r.get("slot"): r for r in rows if isinstance(r, dict)}
    drafted_by = f"openrouter:{model} {datetime.now(UTC).date().isoformat()}"
    kept: dict[str, dict[str, Any]] = {}
    failed: dict[str, list[str]] = {}
    for s in slots:
        row = by_slot.get(s.slot)
        if row is None:
            failed[s.slot] = ["missing from the response"]
            continue
        problems = check_row(row, s, redactor)
        if problems:
            failed[s.slot] = problems
            continue
        kept[s.slot] = {
            "slot": s.slot,
            "subject": row["subject"].strip(),
            "body": row["body"].strip(),
            "channel": row["channel"],
            "topic": s.topic,
            "draft_intent": s.intent,
            "draft_security": s.security,
            "drafted_by": drafted_by,
        }
    return BatchOutcome(kept, failed, resp.usage.cost_usd, seconds)


def _slug(model: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "-", model.lower()).strip("-")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    tmp.replace(path)


@dataclass(frozen=True)
class TrialResult:
    model: str
    outcome: BatchOutcome
    path: Path


def run_trial(
    provider: ProviderProtocol,
    model: str,
    *,
    work_dir: Path,
    system_prompt: str,
    redactor: Redactor,
    budget_usd: float = BUDGET_USD,
    seed: int = SEED,
) -> TrialResult:
    """Draft batch 1 with one candidate; its kept rows become batch 1 if it wins."""
    slots = [s for s in plan_slots(seed) if s.batch == 1]
    outcome = _draft(
        provider,
        model,
        slots,
        system_prompt=system_prompt,
        redactor=redactor,
        avoid=[],
        ledger=work_dir / "ledger.jsonl",
        budget_usd=budget_usd,
        phase="trial",
    )
    path = work_dir / f"trial-{_slug(model)}.jsonl"
    _write_jsonl(path, [outcome.kept[s.slot] for s in slots if s.slot in outcome.kept])
    return TrialResult(model, outcome, path)


@dataclass(frozen=True)
class DraftResult:
    out: Path
    rows: int
    calls: int
    cost_usd: float  # this run's calls only; the ledger holds the total
    spent_usd: float  # the ledger's total, trials included


def run_draft(
    provider: ProviderProtocol,
    model: str,
    *,
    work_dir: Path,
    system_prompt: str,
    redactor: Redactor,
    out: Path = OUT_PATH,
    budget_usd: float = BUDGET_USD,
    seed: int = SEED,
) -> DraftResult:
    """Draft every slot the trial did not keep, then write the unlabelled set.

    Progress is saved after every call, so a run cut short by an outage or the
    budget resumes where it stopped instead of paying for its rows again.
    """
    if out.exists():
        raise LabelSetError(f"{out} already exists and may hold labels; move it aside first")
    trial = work_dir / f"trial-{_slug(model)}.jsonl"
    if not trial.is_file():
        raise LabelSetError(f"no trial for {model}: run the trial with this model first")
    progress = work_dir / f"draft-{_slug(model)}.jsonl"
    slots = plan_slots(seed)
    kept = {r["slot"]: r for r in _read_jsonl(progress if progress.is_file() else trial)}
    ledger = work_dir / "ledger.jsonl"
    calls, cost = 0, 0.0
    last_failed: dict[str, list[str]] = {}

    for round_no in range(MAX_ROUNDS + 1):
        ordered = [kept[s.slot] for s in slots if s.slot in kept]
        for slot_id in near_duplicates(ordered):
            del kept[slot_id]
            last_failed[slot_id] = ["nearly repeats another item on its topic"]
        todo = [s for s in slots if s.slot not in kept]
        if not todo:
            break
        if round_no == MAX_ROUNDS:
            _write_jsonl(progress, [kept[s.slot] for s in slots if s.slot in kept])
            detail = "; ".join(
                f"{s.slot}: {', '.join(last_failed.get(s.slot, ['?']))}" for s in todo
            )
            raise LabelSetError(
                f"{len(todo)} slots still fail after {MAX_ROUNDS} rounds "
                f"(progress kept in {progress}): {detail}"
            )
        for i in range(0, len(todo), BATCH_SIZE):
            chunk = todo[i : i + BATCH_SIZE]
            topics = {s.topic for s in chunk}
            avoid = [r["subject"] for r in kept.values() if r["topic"] in topics and r["subject"]]
            outcome = _draft(
                provider,
                model,
                chunk,
                system_prompt=system_prompt,
                redactor=redactor,
                avoid=avoid,
                ledger=ledger,
                budget_usd=budget_usd,
                phase="draft" if round_no == 0 else f"redraft-{round_no}",
            )
            calls, cost = calls + 1, cost + outcome.cost_usd
            kept.update(outcome.kept)
            for slot_id in outcome.kept:
                last_failed.pop(slot_id, None)
            last_failed.update(outcome.failed)
            _write_jsonl(progress, [kept[s.slot] for s in slots if s.slot in kept])

    rows = [kept[s.slot] for s in slots]
    random.Random(seed).shuffle(rows)
    _write_jsonl(
        out,
        [
            {
                "id": f"LS1-{i:03d}",
                "subject": r["subject"],
                "body": r["body"],
                "channel": r["channel"],
                "topic": r["topic"],
                "draft_intent": r["draft_intent"],
                "draft_security": r["draft_security"],
                "work_item_type": None,
                "security": None,
                "label_confidence": None,
                "label_note": None,
                "answer_space": None,
                "drafted_by": r["drafted_by"],
                "labelled_by": None,
                "labelled_at": None,
                "labelled_time": None,
            }
            for i, r in enumerate(rows, start=1)
        ],
    )
    return DraftResult(out, len(rows), calls, cost, _spent(ledger))


# ── Labelling (SPEC §6) ─────────────────────────────────────────────────────

ANSWER_SPACE: Final[dict[str, str]] = {"d2": "d2-v1", "d1": "d1-v2"}
RELABEL_PATH: Final = LABEL_SET_DIR / "relabel_v1.jsonl"
RELABEL_ROWS: Final = 10
# "A day later" (SPEC §6), measured from the first pass's last label, with
# room to start the relabel a few hours earlier in the day than the sitting ended.
RELABEL_AFTER: Final = timedelta(hours=20)
# Longer than the one sitting SPEC §6 expects (80–90 minutes).
_SITTING: Final = timedelta(hours=2)

_TYPE_KEYS: Final = {"i": "incident", "r": "service_request"}
_SECURITY_KEYS: Final = {"y": "yes", "n": "no"}
_CONFIDENCE_KEYS: Final = {"h": "high", "l": "low"}

Ask = Callable[[str], str]
Show = Callable[[str], None]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _labelled(by: str, at: datetime) -> dict[str, str]:
    """Who labelled a row and when: the UTC date SPEC §2 records, and the moment."""
    at = at.astimezone(UTC)
    return {
        "labelled_by": by,
        "labelled_at": at.date().isoformat(),
        "labelled_time": at.isoformat(timespec="seconds"),
    }


def _last_labelled(rows: list[dict[str, Any]]) -> datetime:
    """When the last of these rows was labelled, or the latest it can have been.

    A row labelled before ``labelled_time`` was recorded has only the UTC date
    its sitting began on, and a sitting can run past midnight, so it counts
    as labelled a sitting's length after the end of that day.
    """

    def at(row: dict[str, Any]) -> datetime:
        if row.get("labelled_time"):
            return datetime.fromisoformat(row["labelled_time"])
        day = datetime.fromisoformat(row["labelled_at"]).replace(tzinfo=UTC)
        return day + timedelta(days=1) + _SITTING

    return max(at(r) for r in rows)


def _ask_choice(ask: Ask, prompt: str, keys: dict[str, str], *, nav: bool) -> str:
    """One of ``keys``, asked again until it is; with ``nav``, also u or q."""
    while True:
        answer = ask(prompt).strip().lower()
        if answer in keys:
            return keys[answer]
        if nav and answer in ("u", "q"):
            return answer


def _ask_labels(
    row: dict[str, Any], n: int, total: int, ask: Ask, show: Show, *, note: bool
) -> dict[str, Any] | str:
    """Show what the labeller may see, and nothing else; return the labels or u / q."""
    show(f"\n── {row['id']} ({n}/{total}) · {row['channel']} ──")
    show(f"Subject: {row['subject'] or '(none)'}")
    show(row["body"] or "(no body)")
    kind = _ask_choice(ask, "type? [i]ncident / [r]equest  (u back, q quit)", _TYPE_KEYS, nav=True)
    if kind in ("u", "q"):
        return kind
    labels: dict[str, Any] = {
        "work_item_type": kind,
        "security": _ask_choice(ask, "security? [y]es / [n]o", _SECURITY_KEYS, nav=False),
        "label_confidence": _ask_choice(
            ask, "confidence? [h]igh / [l]ow", _CONFIDENCE_KEYS, nav=False
        ),
    }
    if note:
        labels["label_note"] = ask("note (enter to skip)").strip() or None
    return labels


def _label_loop(
    targets: list[dict[str, Any]],
    source: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    ask: Ask,
    show: Show,
    stamp: Callable[[], dict[str, Any]],
    save: Callable[[], None],
    note: bool,
) -> None:
    """Fill each target's labels in order, stamping and saving each one, until done or q."""

    def next_open(start: int) -> int:
        open_ = (j for j in range(start, len(targets)) if targets[j]["work_item_type"] is None)
        return next(open_, len(targets))

    i = next_open(0)
    while i < len(targets):
        answer = _ask_labels(source(targets[i]), i + 1, len(targets), ask, show, note=note)
        if isinstance(answer, str):
            if answer == "q":
                return
            i = max(i - 1, 0)
            continue
        targets[i].update(answer)
        targets[i].update(stamp())
        save()
        i = next_open(i + 1)


@dataclass(frozen=True)
class LabelResult:
    labelled: int
    total: int
    low_confidence: int
    type_splits: int  # the drafter meant one type and the labeller chose the other
    security_splits: int

    @property
    def finished(self) -> bool:
        return self.labelled == self.total


def label_rows(
    path: Path = OUT_PATH, *, by: str, ask: Ask, show: Show, clock: Clock = _utc_now
) -> LabelResult:
    """Label the drafted set blind: each row shows its subject, body and channel only.

    What the drafter intended, and the topic, stay hidden; afterwards only
    counts are reported, never which rows, so tomorrow's relabel stays blind.
    Each row is stamped with the moment it is labelled, which the relabel's
    wait is measured from.
    """
    if not path.is_file():
        raise LabelSetError(f"{path} not found: draft the set first")
    rows = _read_jsonl(path)
    _label_loop(
        rows,
        lambda r: r,
        ask=ask,
        show=show,
        stamp=lambda: {"answer_space": dict(ANSWER_SPACE), **_labelled(by, clock())},
        save=lambda: _write_jsonl(path, rows),
        note=True,
    )
    done = [r for r in rows if r["work_item_type"] is not None]
    return LabelResult(
        labelled=len(done),
        total=len(rows),
        low_confidence=sum(r["label_confidence"] == "low" for r in done),
        type_splits=sum(
            r["draft_intent"] != "ambiguous" and r["draft_intent"] != r["work_item_type"]
            for r in done
        ),
        security_splits=sum(r["draft_security"] != r["security"] for r in done),
    )


@dataclass(frozen=True)
class RelabelResult:
    relabelled: int
    total: int
    type_agree: int
    security_agree: int

    @property
    def finished(self) -> bool:
        return self.relabelled == self.total


def relabel_rows(
    path: Path = OUT_PATH,
    *,
    by: str,
    ask: Ask,
    show: Show,
    out: Path = RELABEL_PATH,
    clock: Clock = _utc_now,
    rng: random.Random | None = None,
) -> RelabelResult:
    """Relabel 10 random rows blind, a day after the first pass (SPEC §6).

    Until ``RELABEL_AFTER`` has passed since the first pass's last label it
    refuses, before a sample is drawn or a row shown. The sample is written to
    ``out`` before the first question, so a run cut short resumes on the same
    rows. The first-pass labels are never shown.
    """
    if not path.is_file():
        raise LabelSetError(f"{path} not found: draft the set first")
    rows = _read_jsonl(path)
    if any(r["work_item_type"] is None for r in rows):
        raise LabelSetError("label every row first; the relabel samples the finished set")
    now = clock()
    opens = _last_labelled(rows) + RELABEL_AFTER
    if now < opens:
        minutes = math.ceil((opens - now).total_seconds() / 60)
        raise LabelSetError(
            "too soon: SPEC §6 relabels a day after the first pass, once its labels are"
            f" forgotten; come back after {opens.astimezone():%Y-%m-%d %H:%M %Z}"
            f" (in {minutes // 60}h{minutes % 60:02d}m)"
        )
    if out.is_file():
        picks = _read_jsonl(out)
    else:
        sample = (rng or random.Random()).sample([r["id"] for r in rows], RELABEL_ROWS)
        picks = [
            {"id": row_id, "work_item_type": None, "security": None, "label_confidence": None}
            for row_id in sample
        ]
        _write_jsonl(out, picks)
    by_id = {r["id"]: r for r in rows}
    _label_loop(
        picks,
        lambda p: by_id[p["id"]],
        ask=ask,
        show=show,
        stamp=lambda: _labelled(by, clock()),
        save=lambda: _write_jsonl(out, picks),
        note=False,
    )
    done = [p for p in picks if p["work_item_type"] is not None]
    return RelabelResult(
        relabelled=len(done),
        total=len(picks),
        type_agree=sum(p["work_item_type"] == by_id[p["id"]]["work_item_type"] for p in done),
        security_agree=sum(p["security"] == by_id[p["id"]]["security"] for p in done),
    )


# ── Reviewing the security column (#225) ────────────────────────────────────

# The d1-v1 review of the security labels the drafter disagreed with (#225),
# kept as the record of what it changed; d1-v2's relabel superseded it.
REVIEW_PATH: Final = LABEL_SET_DIR / "security_review_v1.jsonl"
SECURITY_RELABEL_PATH: Final = LABEL_SET_DIR / "security_d1_v2.jsonl"


@dataclass(frozen=True)
class SecurityRelabelResult:
    labelled: int
    total: int
    changed: int  # rows the new answer space labels the other way

    @property
    def finished(self) -> bool:
        return self.labelled == self.total


def relabel_security(
    path: Path = OUT_PATH,
    *,
    by: str,
    ask: Ask,
    show: Show,
    version: str,
    definition: str,
    out: Path = SECURITY_RELABEL_PATH,
    clock: Clock = _utc_now,
) -> SecurityRelabelResult:
    """Label every row's security column again, blind, against a new answer space (#225).

    The labeller sees a row's subject, body and channel and the new
    definition; the label given before and what the drafter intended stay
    hidden. Each answer goes to ``out``, which keeps a pass cut short
    resumable. Once every row has an answer the set is rewritten: ``security``
    takes the new label, the old one is kept beside it as ``security_d1_v1``,
    and the row records the version it was labelled against.
    """
    if not path.is_file():
        raise LabelSetError(f"{path} not found: draft the set first")
    rows = _read_jsonl(path)
    if any(r["security"] is None for r in rows):
        raise LabelSetError("label every row first; the relabel reads the finished set")
    if out.is_file():
        answers = _read_jsonl(out)
    else:
        answers = [{"id": r["id"], "before": r["security"], "after": None} for r in rows]
        _write_jsonl(out, answers)
    by_id = {r["id"]: r for r in rows}
    # A finished pass has already written its answers in, so a row may hold either.
    moved = [
        e["id"] for e in answers if by_id[e["id"]]["security"] not in (e["before"], e["after"])
    ]
    if moved:
        raise LabelSetError(
            f"the set changed under the saved pass ({', '.join(moved)}); "
            f"move {out} aside and start again"
        )

    show(f"{version}, security: {definition}")
    i = next((j for j, e in enumerate(answers) if e["after"] is None), len(answers))
    while i < len(answers):
        row = by_id[answers[i]["id"]]
        show(f"\n── {row['id']} ({i + 1}/{len(answers)}) · {row['channel']} ──")
        show(f"Subject: {row['subject'] or '(none)'}")
        show(row["body"] or "(no body)")
        answer = _ask_choice(
            ask, "security? [y]es / [n]o  (u back, q quit)", _SECURITY_KEYS, nav=True
        )
        if answer == "q":
            break
        if answer == "u":
            i = max(i - 1, 0)
            continue
        answers[i].update(after=answer, **_labelled(by, clock()))
        _write_jsonl(out, answers)
        i += 1

    done = [e for e in answers if e["after"] is not None]
    if len(done) == len(answers):
        for e in answers:
            row = by_id[e["id"]]
            # The first pass's d1-v1 label, kept once: a later pass must not overwrite it.
            row.setdefault("security_d1_v1", e["before"])
            row["security"] = e["after"]
            row["answer_space"] = {**(row.get("answer_space") or {}), "d1": version}
        _write_jsonl(path, rows)
    return SecurityRelabelResult(
        labelled=len(done),
        total=len(answers),
        changed=sum(e["after"] != e["before"] for e in done),
    )


# ── Decision 9: a known fix among the handbook pages kb_search offers (#226) ─

CANDIDATES_PATH: Final = LABEL_SET_DIR / "candidates_d9_v1.jsonl"
EXCERPT_CHARS: Final = 600


def build_candidates(
    rows: list[dict[str, Any]],
    *,
    search: Callable[[str], Sequence[Any]],
    describe: Callable[[str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Each row's candidate pages: its kb_search hits, grouped by page in rank order.

    The query is what the run's prefetch searches on, the subject then the
    body. A page appears once, with its best hit as the excerpt: what the
    labeller is shown, and what the engines will be. Written once and kept, so
    a later KB build does not move the candidates under the labels.
    """
    out = []
    for row in rows:
        query = "\n".join(text for text in (row["subject"], row["body"]) if text)
        pages: dict[str, dict[str, Any]] = {}
        for hit in search(query):
            if hit.document_id not in pages:
                pages[hit.document_id] = {
                    **describe(hit.document_id),
                    "document_id": hit.document_id,
                    "excerpt": hit.content[:EXCERPT_CHARS],
                }
        out.append({"id": row["id"], "candidates": list(pages.values())})
    return out


@dataclass(frozen=True)
class KnownFixResult:
    labelled: int
    total: int
    with_a_fix: int

    @property
    def finished(self) -> bool:
        return self.labelled == self.total


def _ask_pages(ask: Ask, count: int) -> list[int] | str:
    """The candidate numbers that fix the row (0 for none), asked again until valid; or u / q."""
    prompt = "known fix? page numbers, e.g. 1,3; 0 for none  (u back, q quit)"
    while True:
        answer = ask(prompt).strip().lower()
        if answer in ("u", "q"):
            return answer
        if answer == "0":
            return []
        parts = [part.strip() for part in answer.split(",")]
        if parts and all(p.isdigit() and 1 <= int(p) <= count for p in parts):
            return list(dict.fromkeys(int(p) for p in parts))


def label_known_fix(
    path: Path = OUT_PATH,
    *,
    candidates: Path = CANDIDATES_PATH,
    by: str,
    ask: Ask,
    show: Show,
    version: str,
    definition: str,
    clock: Clock = _utc_now,
) -> KnownFixResult:
    """Label which candidate pages are a known fix for each row, or none (decision 9).

    Each row shows its subject, body and channel and its candidate pages, each
    with its title, path and excerpt; no engine has been asked. Each answer is
    saved on the row as it is given, so a rerun picks up at the first open row.
    """
    if not path.is_file():
        raise LabelSetError(f"{path} not found: draft the set first")
    if not candidates.is_file():
        raise LabelSetError(f"no candidates at {candidates}: run `opspilot labelset candidates`")
    rows = _read_jsonl(path)
    offered = {c["id"]: c["candidates"] for c in _read_jsonl(candidates)}
    if missing := [r["id"] for r in rows if r["id"] not in offered]:
        raise LabelSetError(f"no candidates for {', '.join(missing)}; rebuild the candidates")

    def next_open(start: int) -> int:
        return next((j for j in range(start, len(rows)) if "known_fix" not in rows[j]), len(rows))

    show(f"{version}: a page is a known fix when {definition}")
    i = next_open(0)
    while i < len(rows):
        row, pages = rows[i], offered[rows[i]["id"]]
        show(f"\n── {row['id']} ({i + 1}/{len(rows)}) · {row['channel']} ──")
        show(f"Subject: {row['subject'] or '(none)'}")
        show(row["body"] or "(no body)")
        for n, page in enumerate(pages, start=1):
            show(f"\n  [{n}] {page['title']} · {page['source_path']}")
            show("      " + page["excerpt"].replace("\n", "\n      "))
        answer = _ask_pages(ask, len(pages))
        if answer == "q":
            break
        if answer == "u":
            i = max(i - 1, 0)
            continue
        assert isinstance(answer, list)
        at = clock().astimezone(UTC).isoformat(timespec="seconds")
        row.update(
            known_fix=[pages[n - 1]["source_path"] for n in answer],
            known_fix_labelled_by=by,
            known_fix_labelled_time=at,
            answer_space={**(row.get("answer_space") or {}), "d9": version},
        )
        _write_jsonl(path, rows)
        i = next_open(i + 1)

    done = [r for r in rows if "known_fix" in r]
    return KnownFixResult(
        labelled=len(done), total=len(rows), with_a_fix=sum(bool(r["known_fix"]) for r in done)
    )


# ── A pass over one type's rows: Impact, Urgency, team (#227, #228), catalog item (#231) ─


@dataclass(frozen=True)
class LabelPassResult:
    labelled: int
    total: int
    counts: dict[str, dict[str, int]]  # column → answer → rows labelled it

    @property
    def finished(self) -> bool:
        return self.labelled == self.total


def _levels(question: Question) -> dict[str, str]:
    """A question's answers keyed 1, 2, 3 … in the file's order, as the labeller types them."""
    return {str(n): level for n, level in enumerate(question.answers, start=1)}


def label_pass(
    path: Path = OUT_PATH,
    *,
    by: str,
    ask: Ask,
    show: Show,
    columns: dict[str, Question],
    stamp: str,
    of: str = "incident",
    clock: Clock = _utc_now,
) -> LabelPassResult:
    """Label each row of type ``of``, blind, in one pass over ``columns`` (e.g. impact then urgency).

    Only the rows labelled ``of`` are asked: ADR-0040 asks these decisions of
    an Incident, or on the request path of a service request (#231). Each row
    shows its subject, body and channel, and no other label. A row's answers
    are saved as they are given, with ``{stamp}_labelled_by`` and
    ``{stamp}_labelled_time``, so a rerun picks up at the first open row.
    """
    if not path.is_file():
        raise LabelSetError(f"{path} not found: draft the set first")
    rows = _read_jsonl(path)
    if any(r["work_item_type"] is None for r in rows):
        raise LabelSetError(f"label every row's type first; only {of} rows are asked")
    asked = [r for r in rows if r["work_item_type"] == of]
    keys = {column: _levels(q) for column, q in columns.items()}
    first = next(iter(columns))

    for column, q in columns.items():
        show(f"{q.version}: {q.text}")
        for key, answer in keys[column].items():
            show(f"  {key} {answer}: {q.answers[answer]}")

    def prompt(column: str) -> str:
        return f"{column}? " + " · ".join(f"{k} {v}" for k, v in keys[column].items())

    def next_open(start: int) -> int:
        open_ = (j for j in range(start, len(asked)) if first not in asked[j])
        return next(open_, len(asked))

    i = next_open(0)
    while i < len(asked):
        row = asked[i]
        show(f"\n── {row['id']} ({i + 1}/{len(asked)}) · {row['channel']} ──")
        show(f"Subject: {row['subject'] or '(none)'}")
        show(row["body"] or "(no body)")
        answer = _ask_choice(ask, prompt(first) + "  (u back, q quit)", keys[first], nav=True)
        if answer == "q":
            break
        if answer == "u":
            i = max(i - 1, 0)
            continue
        labels = {first: answer}
        for column in list(columns)[1:]:
            labels[column] = _ask_choice(ask, prompt(column), keys[column], nav=False)
        row.update(
            labels,
            **{
                f"{stamp}_labelled_by": by,
                f"{stamp}_labelled_time": clock().astimezone(UTC).isoformat(timespec="seconds"),
            },
            answer_space={
                **(row.get("answer_space") or {}),
                **{q.id: q.version for q in columns.values()},
            },
        )
        _write_jsonl(path, rows)
        i = next_open(i + 1)

    done = [r for r in asked if first in r]
    return LabelPassResult(
        labelled=len(done),
        total=len(asked),
        counts={
            column: {a: sum(r[column] == a for r in done) for a in q.answers}
            for column, q in columns.items()
        },
    )


# ── Decision 3: already open, over duplicates drafted for it (#230) ──────────

DUPLICATE_PROMPT_PATH: Final = LABEL_SET_DIR / "DUPLICATE_PROMPT.md"
DUPLICATES_PATH: Final = LABEL_SET_DIR / "duplicates_d3_v1.jsonl"
ALREADY_OPEN_PATH: Final = LABEL_SET_DIR / "already_open_d3_v1.jsonl"
OPEN_ITEMS: Final = 5  # open Work items offered with each Work item


def _duplicate_message(batch: list[dict[str, Any]]) -> str:
    items = [
        {"of": r["id"], "subject": r["subject"], "body": r["body"], "channel": r["channel"]}
        for r in batch
    ]
    return "\n".join(
        [
            "Write one duplicate for each of these Work items:",
            "```json",
            json.dumps(items, indent=1),
            "```",
        ]
    )


def draft_duplicates(
    rows: list[dict[str, Any]],
    provider: ProviderProtocol,
    model: str,
    *,
    system_prompt: str,
    redactor: Redactor,
    ledger: Path,
    budget_usd: float = BUDGET_USD,
) -> list[dict[str, Any]]:
    """One duplicate of each Incident: the same problem, told by someone else (#230).

    Each is checked as the set's rows were, and must not nearly repeat the
    Incident it was written from. A batch's failures are drafted again, up to
    ``MAX_ROUNDS`` times; every call's charge goes to ``ledger``, and none
    starts once it reaches ``budget_usd``.
    """
    incidents = {r["id"]: r for r in rows if r["work_item_type"] == "incident"}
    kept: dict[str, dict[str, Any]] = {}
    failed: dict[str, list[str]] = {}
    drafted_by = f"openrouter:{model} {datetime.now(UTC).date().isoformat()}"
    for _ in range(MAX_ROUNDS + 1):
        todo = [r for i, r in incidents.items() if i not in kept]
        if not todo:
            break
        for start in range(0, len(todo), BATCH_SIZE):
            batch = todo[start : start + BATCH_SIZE]
            spent = _spent(ledger)
            if spent >= budget_usd:
                raise LabelSetError(f"budget reached: ${spent:.4f} of ${budget_usd:.2f} spent")
            resp = provider.chat(
                [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=_duplicate_message(batch)),
                ],
                model=model,
                params=SamplingParams(temperature=0.9, max_tokens=8_000),
                timeout_ms=300_000,
            )
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with ledger.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {"phase": "duplicates", "model": model, "cost_usd": resp.usage.cost_usd}
                    )
                    + "\n"
                )
            parsed, err = _parse_summary_json(resp.content)
            drafted = parsed.get("rows") if err is None else None
            by_of = {d.get("of"): d for d in drafted or [] if isinstance(d, dict)}
            for r in batch:
                d = by_of.get(r["id"])
                if d is None:
                    failed[r["id"]] = [err or "missing from the response"]
                    continue
                subject, body = d.get("subject"), d.get("body")
                if not isinstance(subject, str) or not isinstance(body, str):
                    failed[r["id"]] = ["subject and body must be strings"]
                    continue
                problems = _text_problems(subject, body, d.get("channel"), redactor)
                if (
                    SequenceMatcher(None, body.lower(), r["body"].lower()).ratio()
                    >= _NEAR_DUPLICATE
                ):
                    problems.append("it nearly repeats the Incident it was written from")
                if problems:
                    failed[r["id"]] = problems
                    continue
                kept[r["id"]] = {
                    "of": r["id"],
                    "subject": subject.strip(),
                    "body": body.strip(),
                    "channel": d["channel"],
                    "drafted_by": drafted_by,
                }
                failed.pop(r["id"], None)
    if missing := [i for i in incidents if i not in kept]:
        detail = "; ".join(f"{i}: {', '.join(failed.get(i, ['?']))}" for i in missing)
        raise LabelSetError(
            f"{len(missing)} duplicates still fail after {MAX_ROUNDS} rounds: {detail}"
        )
    return [kept[i] for i in incidents]


def build_already_open(
    rows: list[dict[str, Any]], duplicates: list[dict[str, Any]], *, seed: int = 230
) -> list[dict[str, Any]]:
    """The Work items decision 3 is measured on, each with its open Work items (#230).

    Each duplicate is offered the Incident it was written from among four
    others, two on its topic where there are two; each Incident is offered five
    others and not its duplicate. Every item gets the same number of open Work
    items, in shuffled order, and the items are shuffled together, so neither
    the count nor the order says which kind an item is.
    """
    incidents = [r for r in rows if r["work_item_type"] == "incident"]
    by_id = {r["id"]: r for r in incidents}
    rng = random.Random(seed)

    def others(exclude: set[str], topic: str, count: int) -> list[dict[str, Any]]:
        same = [r for r in incidents if r["topic"] == topic and r["id"] not in exclude]
        rng.shuffle(same)
        picked = same[:2]
        rest = [r for r in incidents if r["id"] not in exclude and r not in picked]
        return picked + rng.sample(rest, count - len(picked))

    def offered(open_items: list[dict[str, Any]]) -> list[dict[str, str]]:
        rng.shuffle(open_items)
        return [{"key": r["id"], "subject": r["subject"], "body": r["body"]} for r in open_items]

    items = []
    for d in duplicates:
        of = by_id[d["of"]]
        open_items = [of, *others({of["id"]}, of["topic"], OPEN_ITEMS - 1)]
        items.append({"kind": "duplicate", **d, "candidates": offered(open_items)})
    for r in incidents:
        open_items = others({r["id"]}, r["topic"], OPEN_ITEMS)
        item = {"kind": "incident", "of": r["id"], "subject": r["subject"], "body": r["body"]}
        items.append({**item, "channel": r["channel"], "candidates": offered(open_items)})
    rng.shuffle(items)
    return [{"id": f"AO-{n:03d}", **item, "same": None} for n, item in enumerate(items, start=1)]


@dataclass(frozen=True)
class AlreadyOpenResult:
    labelled: int
    total: int
    matched: int  # items labelled the same problem as one of their open Work items

    @property
    def finished(self) -> bool:
        return self.labelled == self.total


def label_already_open(
    path: Path = ALREADY_OPEN_PATH,
    *,
    by: str,
    ask: Ask,
    show: Show,
    question: Question,
    clock: Clock = _utc_now,
) -> AlreadyOpenResult:
    """Label which open Work item, if any, each item repeats, blind (decision 3, #230).

    Each item shows its subject, body and channel, and its open Work items by
    number, with their subject and body; not their keys, not which item was
    drafted from which. Each answer is saved as it is given.
    """
    if not path.is_file():
        raise LabelSetError(f"{path} not found: run `opspilot labelset draft-duplicates` first")
    items = _read_jsonl(path)

    def next_open(start: int) -> int:
        return next((j for j in range(start, len(items)) if items[j]["same"] is None), len(items))

    show(f"{question.version}: {question.text}")
    show(f"  none: {question.answers['none']}")
    i = next_open(0)
    while i < len(items):
        item = items[i]
        show(f"\n── {item['id']} ({i + 1}/{len(items)}) · {item['channel']} ──")
        show(f"Subject: {item['subject'] or '(none)'}")
        show(item["body"] or "(no body)")
        show("\nOpen Work items:")
        for n, c in enumerate(item["candidates"], start=1):
            show(f"  [{n}] {c['subject'] or '(no subject)'}")
            show("      " + (c["body"] or "(no body)").replace("\n", "\n      "))
        keys = {str(n): c["key"] for n, c in enumerate(item["candidates"], start=1)} | {"0": "none"}
        answer = _ask_choice(
            ask,
            f"same problem? 1–{len(item['candidates'])}, or 0 for none  (u back, q quit)",
            keys,
            nav=True,
        )
        if answer == "q":
            break
        if answer == "u":
            i = max(i - 1, 0)
            continue
        item.update(
            same=answer,
            same_labelled_by=by,
            same_labelled_time=clock().astimezone(UTC).isoformat(timespec="seconds"),
            answer_space={"d3": question.version},
        )
        _write_jsonl(path, items)
        i = next_open(i + 1)

    done = [it for it in items if it["same"] is not None]
    return AlreadyOpenResult(
        labelled=len(done), total=len(items), matched=sum(it["same"] != "none" for it in done)
    )
