"""Distilling a closed Working set into a Skill (ADR-0026, revised by ADR-0036).

Three refusals carry the design, and they are what these mostly pin.

**A set closed by the inactivity fallback is not distillable.** It was abandoned,
not solved, and an abandoned investigation has no procedure in it.

**The stopping condition and allowed_tools come back blank.** A run that went
well never exercised either, so nothing in the record could supply them — and a
plausible guess reads well, gets skimmed, and gets merged. A blank cannot be
rubber-stamped.

**An amendment does not widen what a Skill may do.** Revising the body is not a
licence to add tools.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from opspilot.consultation import (
    MIN_CONSULTATIONS,
    ConsultationStore,
    NotDistillableError,
    WorkingSetStore,
    draft,
    gather,
    stage,
)
from opspilot.consultation.distil import TODO_STOP
from opspilot.skills import Skill, parse_skill_md


class _Provider:
    def __init__(self, body: str = "## 1. Scope it\n\nCheck the array first.") -> None:
        self.body = body
        self.seen: list[str] = []

    def chat(self, messages: list[Any], **kwargs: Any) -> Any:
        self.seen = [m.content for m in messages]

        class _R:
            content = self.body

        return _R()


@pytest.fixture
def stores(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "a.db")
    return WorkingSetStore(conn), ConsultationStore(conn)


def _loop(stores, *, conversations: int = MIN_CONSULTATIONS, close: bool = True):
    working, consultations = stores
    ws = working.open(owner="alice", title="dc-1 storage latency", scope="dc-1")
    for i in range(conversations):
        con = consultations.start(author="alice", title=f"round {i}", working_set_id=ws.id)
        consultations.append(con.id, role="user", content=f"Latency spiked again, round {i}")
        consultations.append(
            con.id, role="assistant", content=f"Ruled out the switch; checking paths, round {i}"
        )
    if close:
        working.close(ws.id)
    return ws


class TestEligibility:
    def test_a_manually_closed_chain_qualifies(self, stores) -> None:
        ws = _loop(stores)
        source = gather(*stores, ws.id)
        assert source.consultations == MIN_CONSULTATIONS
        assert source.scope == "dc-1"

    def test_an_open_set_is_refused(self, stores) -> None:
        ws = _loop(stores, close=False)
        with pytest.raises(NotDistillableError, match="still open"):
            gather(*stores, ws.id)

    def test_an_abandoned_set_is_refused(self, stores) -> None:
        """Closed by the fallback means abandoned; there is no procedure in it."""
        working, _ = stores
        ws = _loop(stores, close=False)
        working.sweep(now="2030-01-01T00:00:00Z")
        with pytest.raises(NotDistillableError, match="abandoned"):
            gather(*stores, ws.id)

    def test_one_conversation_is_a_question_not_a_loop(self, stores) -> None:
        ws = _loop(stores, conversations=1)
        with pytest.raises(NotDistillableError, match="at least"):
            gather(*stores, ws.id)


class TestInput:
    def test_the_whole_chain_goes_in_dead_ends_included(self, stores) -> None:
        """Keeping only what worked reads like documentation nobody can reproduce."""
        ws = _loop(stores, conversations=3)
        source = gather(*stores, ws.id)
        assert source.transcript.count("Ruled out the switch") == 3
        assert "round 0" in source.transcript and "round 2" in source.transcript


class TestDraft:
    def test_a_new_skill_comes_back_with_blanks(self, stores) -> None:
        source = gather(*stores, _loop(stores).id)
        skill = draft(_Provider(), source, model_name="m")
        assert skill.allowed_tools == []
        assert TODO_STOP in skill.body
        assert "When to stop" in skill.body

    def test_the_prompt_forbids_inventing_them(self, stores) -> None:
        source = gather(*stores, _loop(stores).id)
        provider = _Provider()
        draft(provider, source, model_name="m")
        system = provider.seen[0]
        assert "Do not invent a stopping condition" in system
        assert "Keep the dead ends" in system

    def test_an_amendment_keeps_the_existing_tools(self, stores) -> None:
        """Revising the body is not a licence to widen what the Skill may do."""
        source = gather(*stores, _loop(stores).id)
        existing = Skill(
            id="storage-path-and-array-faults",
            name="Storage path and array faults",
            trigger="use when paths flap",
            body="old body",
            allowed_tools=["kb_search"],
            trust="internal",
        )
        revised = draft(_Provider("new body"), source, model_name="m", amends=existing)
        assert revised.id == existing.id
        assert revised.allowed_tools == ["kb_search"]
        assert revised.body == "new body"
        assert TODO_STOP not in revised.body  # the stop section is the human's, untouched

    def test_an_amendment_returns_the_whole_body_for_diffing(self, stores) -> None:
        source = gather(*stores, _loop(stores).id)
        provider = _Provider("revised")
        draft(
            provider,
            source,
            model_name="m",
            amends=Skill(id="s", name="S", trigger="t", body="original", allowed_tools=[]),
        )
        assert "COMPLETE revised markdown body" in provider.seen[0]
        assert "original" in provider.seen[1]


class TestStaging:
    def test_a_draft_is_written_not_installed(self, stores, tmp_path: Path) -> None:
        """A file on disk produces no commit and no diff; the commit is the admission."""
        source = gather(*stores, _loop(stores).id)
        skill = draft(_Provider(), source, model_name="m")
        path = stage(skill, tmp_path / "skill-drafts")
        assert path.is_file()
        assert "agent_skills" not in str(path)
        back = parse_skill_md(path.read_text(encoding="utf-8"), fallback_id=skill.id)
        assert back.allowed_tools == []
        assert TODO_STOP in back.body
