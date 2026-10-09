"""Label set v1 drafting (#224, judgments/label_set/SPEC.md).

No model is called: a fake drafter reads the slot table out of the user
message and writes one row per slot, so the quotas, the per-row checks, the
redraft loop and the budget can all be exercised offline.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from opspilot.errors import ProviderError
from opspilot.label_set import (
    BATCH_SIZE,
    BATCHES,
    DRAFT_PROMPT_PATH,
    FORMS,
    INTENTS,
    MAX_PER_TOPIC,
    SECURITY_BY_INTENT,
    TOPICS,
    LabelSetError,
    RelabelResult,
    Slot,
    check_row,
    label_rows,
    near_duplicates,
    plan_slots,
    relabel_rows,
    run_draft,
    run_trial,
)
from opspilot.providers.types import ChatResponse, Message, SamplingParams, Usage
from opspilot.redaction import Redactor

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT = (REPO_ROOT / DRAFT_PROMPT_PATH).read_text(encoding="utf-8")
MODEL = "google/gemini-test"


def _subject(slot_id: str, attempt: int = 0) -> str:
    """Letters only, unrelated across slots: never a near-duplicate, never redacted."""
    digest = hashlib.sha1(f"{slot_id}/{attempt}".encode()).hexdigest()[:16]
    return "".join(chr(97 + int(c, 16)) for c in digest)


def _good_row(slot: dict[str, Any], attempt: int = 0) -> dict[str, Any]:
    words = {"one_liner": 5, "long_rambling": 120}.get(slot["form"], 30)
    return {
        "slot": slot["slot"],
        "subject": _subject(slot["slot"], attempt),
        "body": " ".join(["printer"] * words),
        "channel": "email" if slot["form"] == "forwarded_email" else "portal",
        "topic": slot["topic"],
        "draft_intent": slot["intent"],
        "draft_security": slot["security"],
    }


class FakeDrafter:
    """Writes one good row per slot, unless told to spoil a slot's first tries."""

    def __init__(
        self,
        *,
        spoil: dict[str, list[dict[str, Any]]] | None = None,
        cost: float = 0.01,
        finish: str = "stop",
        fail_on_call: int | None = None,
    ) -> None:
        self.spoil = spoil or {}
        self.cost = cost
        self.finish = finish
        self.fail_on_call = fail_on_call
        self.calls: list[list[Message]] = []
        self.attempts: Counter[str] = Counter()

    def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        params: SamplingParams,
        tools: Any = None,
        timeout_ms: int = 90_000,
    ) -> ChatResponse:
        self.calls.append(messages)
        if self.fail_on_call == len(self.calls):
            raise ProviderError("provider down")
        match = re.search(r"```json\n(.*?)\n```", messages[1].content, re.S)
        assert match is not None
        rows = []
        for slot in json.loads(match.group(1)):
            row = _good_row(slot, self.attempts[slot["slot"]])
            self.attempts[slot["slot"]] += 1
            patches = self.spoil.get(slot["slot"])
            if patches:
                row.update(patches.pop(0))
            rows.append(row)
        return ChatResponse(
            content=json.dumps({"rows": rows}),
            finish_reason=self.finish,  # type: ignore[arg-type]
            usage=Usage(input_tokens=100, output_tokens=200, cost_usd=self.cost),
        )


def _trial(tmp_path: Path, drafter: FakeDrafter, **kw: Any) -> Any:
    return run_trial(
        drafter,  # type: ignore[arg-type]
        MODEL,
        work_dir=tmp_path / "work",
        system_prompt=PROMPT,
        redactor=Redactor.from_yaml(),
        **kw,
    )


def _draft(tmp_path: Path, drafter: FakeDrafter, **kw: Any) -> Any:
    return run_draft(
        drafter,  # type: ignore[arg-type]
        MODEL,
        work_dir=tmp_path / "work",
        system_prompt=PROMPT,
        redactor=Redactor.from_yaml(),
        out=tmp_path / "label_set_v1.jsonl",
        **kw,
    )


def _ledger(tmp_path: Path) -> list[dict[str, Any]]:
    text = (tmp_path / "work" / "ledger.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


# ── The plan: the script sets the mix (SPEC §3, §5) ─────────────────────────


class TestPlan:
    def test_every_quota_is_met_exactly(self) -> None:
        slots = plan_slots()
        assert [s.slot for s in slots] == [f"S{n:02d}" for n in range(1, 81)]
        assert Counter(s.intent for s in slots) == INTENTS
        assert Counter(s.intent for s in slots if s.security == "yes") == SECURITY_BY_INTENT
        assert sum(SECURITY_BY_INTENT.values()) >= 12
        assert all(SECURITY_BY_INTENT[i] > 0 for i in INTENTS)
        topics = Counter(s.topic for s in slots)
        assert set(topics) == set(TOPICS)
        assert max(topics.values()) <= MAX_PER_TOPIC
        forms = Counter(s.form for s in slots)
        assert {f: forms[f] for f in FORMS} == FORMS
        assert forms["ordinary"] == 80 - sum(FORMS.values())

    def test_each_batch_carries_its_share(self) -> None:
        slots = plan_slots()
        for b in range(1, BATCHES + 1):
            batch = [s for s in slots if s.batch == b]
            assert len(batch) == BATCH_SIZE
            assert sum(s.intent == "ambiguous" for s in batch) == 2
            assert any(s.security == "yes" for s in batch)

    def test_the_plan_is_fixed_by_its_seed(self) -> None:
        assert plan_slots(224) == plan_slots(224)
        assert plan_slots(224) != plan_slots(225)


# ── One row against its slot (SPEC §2, §3, §4) ──────────────────────────────

_SLOT = Slot("S01", 1, "incident", "no", TOPICS[0], "ordinary")


def _row(**over: Any) -> dict[str, Any]:
    row = {
        "slot": "S01",
        "subject": "VPN drops every few minutes",
        "body": "Since 09:15 the GlobalProtect client keeps dropping. vpn.example.com is slow.",
        "channel": "email",
        "topic": TOPICS[0],
        "draft_intent": "incident",
        "draft_security": "no",
    }
    return row | over


class TestCheckRow:
    @pytest.fixture
    def redactor(self) -> Redactor:
        return Redactor.from_yaml()

    def test_a_row_that_keeps_to_its_slot_passes(self, redactor: Redactor) -> None:
        assert check_row(_row(), _SLOT, redactor) == []

    def test_an_echo_that_differs_from_the_slot_fails(self, redactor: Redactor) -> None:
        problems = check_row(_row(draft_intent="ambiguous"), _SLOT, redactor)
        assert problems == ["draft_intent is 'ambiguous', the slot says 'incident'"]

    def test_form_lengths_and_the_forwarded_channel(self, redactor: Redactor) -> None:
        def slot(form: str) -> Slot:
            return Slot("S01", 1, "incident", "no", TOPICS[0], form)

        long_body = " ".join(["word"] * 151)
        assert "over 150" in check_row(_row(body=long_body), _SLOT, redactor)[0]
        twelve = " ".join(["word"] * 12)
        assert "not under 12" in check_row(_row(body=twelve), slot("one_liner"), redactor)[0]
        assert check_row(_row(body=""), slot("one_liner"), redactor) == []
        short = " ".join(["word"] * 99)
        assert "not 100 to 150" in check_row(_row(body=short), slot("long_rambling"), redactor)[0]
        chat = _row(channel="chat")
        assert "forwarded email" in check_row(chat, slot("forwarded_email"), redactor)[0]

    @pytest.mark.parametrize(
        "text",
        [
            "Forwarded from jane@example.com",  # an address, even an example one
            "It failed at 09:15:30",  # a time with seconds reads as IPv6
            "Error 0x80070005 on install",  # eight digits read as a phone number
            "Gateway 10.0.0.12 is down",
        ],
    )
    def test_text_the_redactor_would_change_fails(self, redactor: Redactor, text: str) -> None:
        problems = check_row(_row(body=text), _SLOT, redactor)
        assert len(problems) == 1
        assert problems[0].startswith("the redactor would change it")

    def test_only_example_domains_may_appear(self, redactor: Redactor) -> None:
        assert check_row(_row(body="see wiki.example.org/vpn"), _SLOT, redactor) == []
        problems = check_row(_row(body="see portal.acme-corp.com"), _SLOT, redactor)
        assert problems == ["names domains outside example.com/.org: portal.acme-corp.com"]


class TestNearDuplicates:
    def test_a_near_repeat_on_the_same_topic_is_the_later_slot(self) -> None:
        rows = [
            {"slot": "S01", "topic": "a", "subject": "Need VPN access", "body": ""},
            {"slot": "S02", "topic": "a", "subject": "Need VPN access!", "body": ""},
            {"slot": "S03", "topic": "b", "subject": "Need VPN access", "body": ""},
            {"slot": "S04", "topic": "a", "subject": "", "body": "Printer on floor 3 jams"},
            {"slot": "S05", "topic": "a", "subject": "", "body": "Printer on floor 3 jams."},
        ]
        assert near_duplicates(rows) == {"S02", "S05"}


# ── The trial (SPEC §8) ─────────────────────────────────────────────────────


class TestTrial:
    def test_counts_kept_rows_and_records_the_charge(self, tmp_path: Path) -> None:
        drafter = FakeDrafter(cost=0.0123)
        res = _trial(tmp_path, drafter)
        assert len(res.outcome.kept) == 10
        assert res.outcome.failed == {}
        assert res.path.name == "trial-google-gemini-test.jsonl"
        assert len(res.path.read_text(encoding="utf-8").splitlines()) == 10
        [entry] = _ledger(tmp_path)
        assert entry["model"] == MODEL
        assert entry["phase"] == "trial"
        assert entry["cost_usd"] == 0.0123

    def test_the_committed_prompt_is_what_reaches_the_model(self, tmp_path: Path) -> None:
        drafter = FakeDrafter()
        _trial(tmp_path, drafter)
        [messages] = drafter.calls
        assert messages[0].role == "system"
        assert messages[0].content == PROMPT
        batch_one = [s.slot for s in plan_slots() if s.batch == 1]
        assert all(f'"slot": "{s}"' in messages[1].content for s in batch_one)

    def test_a_row_off_its_slot_is_named_and_not_kept(self, tmp_path: Path) -> None:
        drafter = FakeDrafter(spoil={"S03": [{"body": "mail jane@example.com"}]})
        res = _trial(tmp_path, drafter)
        assert len(res.outcome.kept) == 9
        assert list(res.outcome.failed) == ["S03"]
        assert "redactor" in res.outcome.failed["S03"][0]

    def test_a_truncated_response_fails_every_slot(self, tmp_path: Path) -> None:
        res = _trial(tmp_path, FakeDrafter(finish="length"))
        assert res.outcome.kept == {}
        assert {p[0] for p in res.outcome.failed.values()} == {
            "the response was cut off at max_tokens"
        }

    def test_no_call_once_the_budget_is_spent(self, tmp_path: Path) -> None:
        _trial(tmp_path, FakeDrafter(cost=0.6))
        drafter = FakeDrafter()
        with pytest.raises(LabelSetError, match="budget reached"):
            _trial(tmp_path, drafter, budget_usd=0.5)
        assert drafter.calls == []


# ── The draft ───────────────────────────────────────────────────────────────


def _same_topic_pair() -> tuple[str, str]:
    """Two slots outside batch 1 on one topic, the earlier first."""
    first: dict[str, str] = {}
    for s in plan_slots():
        if s.batch == 1:
            continue
        if s.topic in first:
            return first[s.topic], s.slot
        first[s.topic] = s.slot
    raise AssertionError("no two slots share a topic")


class TestDraft:
    def test_writes_80_unlabelled_rows_after_redrafting_the_misses(self, tmp_path: Path) -> None:
        earlier, later = _same_topic_pair()
        trial = FakeDrafter(spoil={"S02": [{"draft_security": "maybe"}]})
        _trial(tmp_path, trial)
        drafter = FakeDrafter(
            spoil={
                later: [{"subject": _subject(earlier)}],  # nearly repeats `earlier`
                "S47": [{"channel": "fax"}],
            }
        )
        res = _draft(tmp_path, drafter)

        rows = [json.loads(line) for line in res.out.read_text(encoding="utf-8").splitlines()]
        assert res.rows == len(rows) == 80
        assert [r["id"] for r in rows] == [f"LS1-{n:03d}" for n in range(1, 81)]
        assert Counter(r["draft_intent"] for r in rows) == INTENTS
        assert sum(r["draft_security"] == "yes" for r in rows) == sum(SECURITY_BY_INTENT.values())
        assert len({r["subject"] for r in rows}) == 80
        assert list(rows[0]) == [
            "id", "subject", "body", "channel", "topic", "draft_intent", "draft_security",
            "work_item_type", "security", "label_confidence", "label_note", "answer_space",
            "drafted_by", "labelled_by", "labelled_at", "labelled_time",
        ]  # fmt: skip
        for r in rows:
            assert r["drafted_by"].startswith(f"openrouter:{MODEL} ")
            for person_field in ("work_item_type", "security", "label_confidence", "label_note"):
                assert r[person_field] is None
        # Shuffled: the ids do not follow the slot order the rows were drafted in.
        assert [r["topic"] for r in rows] != [s.topic for s in plan_slots()]

        phases = [e["phase"] for e in _ledger(tmp_path)]
        assert phases[0] == "trial"
        assert phases.count("draft") == 8  # S02 rides the first pass with the 70 new slots
        assert phases.count("redraft-1") == 1  # the near-repeat and S47, in one call
        redraft = drafter.calls[-1][1].content
        assert f'"slot": "{later}"' in redraft and '"slot": "S47"' in redraft
        assert _subject(earlier) in redraft  # told what was already written on the topic

    def test_refuses_to_overwrite_a_set_that_may_hold_labels(self, tmp_path: Path) -> None:
        _trial(tmp_path, FakeDrafter())
        (tmp_path / "label_set_v1.jsonl").write_text("{}\n", encoding="utf-8")
        drafter = FakeDrafter()
        with pytest.raises(LabelSetError, match="already exists"):
            _draft(tmp_path, drafter)
        assert drafter.calls == []

    def test_needs_the_models_trial_first(self, tmp_path: Path) -> None:
        with pytest.raises(LabelSetError, match="no trial"):
            _draft(tmp_path, FakeDrafter())

    def test_a_run_cut_short_resumes_without_paying_again(self, tmp_path: Path) -> None:
        _trial(tmp_path, FakeDrafter())
        with pytest.raises(ProviderError):
            _draft(tmp_path, FakeDrafter(fail_on_call=3))
        drafter = FakeDrafter()
        res = _draft(tmp_path, drafter)
        assert res.rows == 80
        assert len(drafter.calls) == 5  # batches 2 and 3 were already kept

    def test_slots_that_keep_failing_stop_the_run_and_say_why(self, tmp_path: Path) -> None:
        _trial(tmp_path, FakeDrafter())
        drafter = FakeDrafter(spoil={"S50": [{"topic": "elsewhere"}] * 10})
        with pytest.raises(LabelSetError, match=r"1 slots still fail .* S50: topic is 'elsewhere'"):
            _draft(tmp_path, drafter)
        assert not (tmp_path / "label_set_v1.jsonl").exists()


# ── The CLI ─────────────────────────────────────────────────────────────────


def test_cli_trial_prints_counts_not_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from opspilot import cli

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    drafter = FakeDrafter(spoil={"S04": [{"channel": "fax"}]}, cost=0.002)
    monkeypatch.setattr(cli, "make_provider", lambda provider_id: drafter)

    result = CliRunner().invoke(cli.app, ["labelset", "trial", "--model", MODEL])

    assert result.exit_code == 0, result.output
    assert f"{MODEL}: 9/10 rows kept to their slot · $0.0020" in result.output
    assert "S04: channel 'fax' is not one of email, portal, chat" in result.output
    assert _subject("S01") not in result.output  # the labeller must not see rows
    assert (tmp_path / "label_set_v1" / "trial-google-gemini-test.jsonl").is_file()


# ── Labelling (SPEC §6) ─────────────────────────────────────────────────────

FIRST_PASS_NOTE = "first-pass-note-must-stay-hidden"


def _set_file(tmp_path: Path, n: int, *, labelled: bool = False) -> Path:
    intents = ["incident", "service_request", "ambiguous", "incident"]
    rows = [
        {
            "id": f"LS1-{i:03d}",
            "subject": f"subject {i}",
            "body": f"body {i}",
            "channel": "chat",
            "topic": TOPICS[i % len(TOPICS)],
            "draft_intent": intents[(i - 1) % 4],
            "draft_security": "yes" if i == 1 else "no",
            "work_item_type": "incident" if labelled else None,
            "security": "no" if labelled else None,
            "label_confidence": "high" if labelled else None,
            "label_note": FIRST_PASS_NOTE if labelled else None,
            "answer_space": None,
            "drafted_by": "openrouter:model 2026-10-07",
            "labelled_by": "vicenteliu" if labelled else None,
            "labelled_at": "2026-10-06" if labelled else None,
        }
        for i in range(1, n + 1)
    ]
    path = tmp_path / "label_set_v1.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


class Keys:
    """Answers the prompts in order, as a person at the terminal would."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0)


def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _at(when: str) -> Callable[[], datetime]:
    """A clock that always reads ``when``."""
    return lambda: datetime.fromisoformat(when)


def _ticking(start: str, minutes: int) -> Callable[[], datetime]:
    """A clock that moves on ``minutes`` every time it is read."""
    reads = itertools.count()
    return lambda: datetime.fromisoformat(start) + timedelta(minutes=minutes * next(reads))


class TestLabel:
    def test_labels_every_row_and_shows_nothing_but_subject_body_channel(
        self, tmp_path: Path
    ) -> None:
        path = _set_file(tmp_path, 4)
        shown: list[str] = []
        keys = Keys(
            *("i", "y", "h", ""),
            *("r", "y", "l", "needs a second look"),
            *("r", "n", "h", ""),
            *("r", "n", "h", ""),
        )
        res = label_rows(
            path,
            by="vicenteliu",
            ask=keys,
            show=shown.append,
            clock=_at("2026-10-07T12:00:00+00:00"),
        )

        assert res.finished and res.labelled == res.total == 4
        assert res.low_confidence == 1
        assert res.type_splits == 1  # LS1-004: drafted incident, labelled request
        assert res.security_splits == 1  # LS1-002: drafted no, labelled yes
        rows = _read(path)
        types = [r["work_item_type"] for r in rows]
        assert types == ["incident", "service_request", "service_request", "service_request"]
        assert rows[1]["label_note"] == "needs a second look" and rows[0]["label_note"] is None
        for r in rows:
            assert r["answer_space"] == {"d2": "d2-v1", "d1": "d1-v1"}
            assert (r["labelled_by"], r["labelled_at"], r["labelled_time"]) == (
                "vicenteliu",
                "2026-10-07",
                "2026-10-07T12:00:00+00:00",
            )

        screen = "\n".join(shown + keys.prompts)
        assert "subject 3" in screen and "body 3" in screen and "chat" in screen
        assert "ambiguous" not in screen and "draft" not in screen
        assert not any(topic in screen for topic in TOPICS)

    def test_each_row_is_stamped_when_it_is_labelled_not_when_the_sitting_began(
        self, tmp_path: Path
    ) -> None:
        path = _set_file(tmp_path, 3)
        clock = _ticking("2026-10-08T23:59:00+00:00", minutes=1)
        label_rows(
            path, by="v", ask=Keys(*(["i", "n", "h", ""] * 3)), show=lambda s: None, clock=clock
        )
        rows = _read(path)
        assert [r["labelled_time"] for r in rows] == [
            "2026-10-08T23:59:00+00:00",
            "2026-10-09T00:00:00+00:00",
            "2026-10-09T00:01:00+00:00",
        ]
        assert [r["labelled_at"] for r in rows] == ["2026-10-08", "2026-10-09", "2026-10-09"]

    def test_a_key_outside_the_choices_is_asked_again(self, tmp_path: Path) -> None:
        path = _set_file(tmp_path, 2)
        keys = Keys("x", "i", "maybe", "y", "", "h", "", "q")
        res = label_rows(path, by="v", ask=keys, show=lambda s: None)
        assert res.labelled == 1
        first = _read(path)[0]
        assert (first["work_item_type"], first["security"], first["label_confidence"]) == (
            "incident",
            "yes",
            "high",
        )

    def test_q_saves_and_a_rerun_resumes_at_the_first_open_row(self, tmp_path: Path) -> None:
        path = _set_file(tmp_path, 3)
        res = label_rows(path, by="v", ask=Keys("i", "n", "h", "", "q"), show=lambda s: None)
        assert not res.finished and res.labelled == 1
        assert _read(path)[0]["work_item_type"] == "incident"

        shown: list[str] = []
        keys = Keys("r", "n", "h", "", "r", "n", "l", "")
        res = label_rows(path, by="v", ask=keys, show=shown.append)
        assert res.finished
        assert "LS1-002 (2/3)" in shown[0]

    def test_u_goes_back_and_the_row_is_labelled_again(self, tmp_path: Path) -> None:
        path = _set_file(tmp_path, 2)
        keys = Keys("i", "y", "h", "", "u", "r", "n", "l", "", "q")
        label_rows(path, by="v", ask=keys, show=lambda s: None)
        first, second = _read(path)
        assert (first["work_item_type"], first["security"], first["label_confidence"]) == (
            "service_request",
            "no",
            "low",
        )
        assert second["work_item_type"] is None

    def test_needs_a_drafted_set(self, tmp_path: Path) -> None:
        with pytest.raises(LabelSetError, match="draft the set first"):
            label_rows(tmp_path / "missing.jsonl", by="v", ask=Keys(), show=lambda s: None)


class TestRelabel:
    def test_waits_for_every_row_to_be_labelled(self, tmp_path: Path) -> None:
        path = _set_file(tmp_path, 12)
        with pytest.raises(LabelSetError, match="label every row first"):
            relabel_rows(path, by="v", ask=Keys(), show=lambda s: None, out=tmp_path / "re.jsonl")

    def test_relabels_ten_blind_and_counts_agreement(self, tmp_path: Path) -> None:
        path = _set_file(tmp_path, 12, labelled=True)
        out = tmp_path / "relabel_v1.jsonl"
        shown: list[str] = []
        keys = Keys(*(["r", "n", "h"] + ["i", "n", "h"] * 9))
        res = relabel_rows(
            path,
            by="vicenteliu",
            ask=keys,
            show=shown.append,
            out=out,
            clock=_at("2026-10-08T12:00:00+00:00"),
            rng=random.Random(1),
        )
        assert res.finished and res.total == 10
        assert (res.type_agree, res.security_agree) == (9, 10)
        picks = _read(out)
        assert len({p["id"] for p in picks}) == 10
        assert all(p["labelled_by"] == "vicenteliu" for p in picks)
        assert FIRST_PASS_NOTE not in "\n".join(shown)  # the first pass stays hidden
        assert not any("note" in p for p in keys.prompts)  # the relabel asks no note

    def test_a_cut_short_relabel_resumes_on_the_same_sample(self, tmp_path: Path) -> None:
        path = _set_file(tmp_path, 12, labelled=True)
        out = tmp_path / "relabel_v1.jsonl"
        first = Keys("i", "n", "h", "i", "n", "h", "i", "n", "h", "q")
        res = relabel_rows(
            path, by="v", ask=first, show=lambda s: None, out=out, rng=random.Random(1)
        )
        assert res.relabelled == 3
        sample = [p["id"] for p in _read(out)]

        rest = Keys(*(["i", "n", "h"] * 7))
        res = relabel_rows(
            path, by="v", ask=rest, show=lambda s: None, out=out, rng=random.Random(99)
        )
        assert res.finished
        assert [p["id"] for p in _read(out)] == sample


class TestRelabelWaitsADay:
    """SPEC §6 relabels a day later so the first-pass labels are forgotten.

    On 2026-10-08 a sitting began before 17:00 PDT and ended at 18:09 PDT,
    after midnight UTC, and a relabel ten minutes later passed a check that
    compared UTC dates.
    """

    def _labelled_across_utc_midnight(self, tmp_path: Path) -> Path:
        path = _set_file(tmp_path, 12)
        keys = Keys(*(["i", "n", "h", ""] * 12))
        clock = _ticking("2026-10-08T23:50:00+00:00", minutes=7)  # the last row at 01:07
        label_rows(path, by="v", ask=keys, show=lambda s: None, clock=clock)
        return path

    def _relabel(self, path: Path, now: str) -> RelabelResult:
        out = path.with_name("re.jsonl")
        return relabel_rows(
            path, by="v", ask=Keys("q"), show=lambda s: None, out=out, clock=_at(now)
        )

    def test_ten_minutes_after_a_sitting_that_crossed_utc_midnight_is_refused(
        self, tmp_path: Path
    ) -> None:
        path = self._labelled_across_utc_midnight(tmp_path)
        out = tmp_path / "re.jsonl"
        keys = Keys()
        shown: list[str] = []
        with pytest.raises(LabelSetError, match="a day after the first pass"):
            relabel_rows(
                path,
                by="v",
                ask=keys,
                show=shown.append,
                out=out,
                clock=_at("2026-10-09T01:17:00+00:00"),
            )
        assert not out.exists() and not shown and not keys.prompts  # no sample, no row seen

    def test_a_day_after_the_sitting_it_proceeds(self, tmp_path: Path) -> None:
        path = self._labelled_across_utc_midnight(tmp_path)
        out = tmp_path / "re.jsonl"
        shown: list[str] = []
        res = relabel_rows(
            path,
            by="v",
            ask=Keys("q"),
            show=shown.append,
            out=out,
            clock=_at("2026-10-10T01:07:00+00:00"),
        )
        assert res.total == 10 and out.is_file()
        assert "(1/10)" in shown[0]

    def test_it_opens_twenty_hours_after_the_last_label(self, tmp_path: Path) -> None:
        path = self._labelled_across_utc_midnight(tmp_path)
        with pytest.raises(LabelSetError, match=r"\(in 0h01m\)"):
            self._relabel(path, "2026-10-09T21:06:00+00:00")
        assert self._relabel(path, "2026-10-09T21:07:00+00:00").total == 10

    def test_the_wait_counts_from_the_last_row_labelled(self, tmp_path: Path) -> None:
        path = _set_file(tmp_path, 12)
        first = Keys(*(["i", "n", "h", ""] * 11), "q")
        label_rows(
            path, by="v", ask=first, show=lambda s: None, clock=_at("2026-10-01T12:00:00+00:00")
        )
        last = Keys("i", "n", "h", "")
        label_rows(
            path, by="v", ask=last, show=lambda s: None, clock=_at("2026-10-09T01:00:00+00:00")
        )
        with pytest.raises(LabelSetError, match="a day after the first pass"):
            self._relabel(path, "2026-10-09T01:10:00+00:00")

    @pytest.mark.parametrize(
        "now",
        ["2026-10-06T23:00:00+00:00", "2026-10-07T01:19:00+00:00", "2026-10-07T21:59:00+00:00"],
        ids=["same UTC day", "next UTC day", "a minute short"],
    )
    def test_a_row_with_only_a_date_waits_from_a_sitting_past_the_end_of_that_day(
        self, tmp_path: Path, now: str
    ) -> None:
        path = _set_file(tmp_path, 12, labelled=True)  # labelled_at 2026-10-06 and no time
        with pytest.raises(LabelSetError, match="a day after the first pass"):
            self._relabel(path, now)
        assert self._relabel(path, "2026-10-07T22:00:00+00:00").total == 10


def test_cli_label_prints_counts_once_the_set_is_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opspilot import cli

    path = _set_file(tmp_path, 2)
    keys = "i\ny\nh\n\nr\nn\nl\nunsure\n"
    result = CliRunner().invoke(
        cli.app, ["labelset", "label", "--by", "vicenteliu", "--set", str(path)], input=keys
    )
    assert result.exit_code == 0, result.output
    assert "all 2 labelled · 1 low-confidence" in result.output
    assert "In 20 hours or later: opspilot labelset relabel" in result.output
    assert "LS1-" not in result.output.split("all 2 labelled")[1]  # counts, never which rows
    assert _read(path)[1]["label_note"] == "unsure"


def test_cli_relabel_refuses_too_soon_and_says_when(tmp_path: Path) -> None:
    from opspilot import cli

    path = _set_file(tmp_path, 12)
    label_rows(path, by="v", ask=Keys(*(["i", "n", "h", ""] * 12)), show=lambda s: None)
    out = tmp_path / "re.jsonl"
    result = CliRunner().invoke(
        cli.app, ["labelset", "relabel", "--by", "v", "--set", str(path), "--out", str(out)]
    )
    assert result.exit_code == 1
    message = " ".join(result.output.split())
    assert "too soon" in message and "(in 20h00m)" in message
    assert not out.exists()
