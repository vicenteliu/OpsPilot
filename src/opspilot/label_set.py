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
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Final

from .errors import OpsPilotError
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
    if not (subject.strip() or body.strip()):
        problems.append("the item is empty")
    if channel not in CHANNELS:
        problems.append(f"channel {channel!r} is not one of {', '.join(CHANNELS)}")
    words = len(body.split())
    if words > 150:
        problems.append(f"the body is {words} words, over 150")
    if slot.form == "one_liner" and words >= 12:
        problems.append(f"a one-liner's body is {words} words, not under 12")
    if slot.form == "long_rambling" and not 100 <= words <= 150:
        problems.append(f"a long item's body is {words} words, not 100 to 150")
    if slot.form == "forwarded_email" and channel != "email":
        problems.append(f"a forwarded email came in by {channel!r}")
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
            }
            for i, r in enumerate(rows, start=1)
        ],
    )
    return DraftResult(out, len(rows), calls, cost, _spent(ledger))
