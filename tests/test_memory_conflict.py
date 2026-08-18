"""Memory ↔ KB disagreements, detected when an answer is composed.

The timing is the decision. At write time the human is present and has just
confirmed the entry, so a prompt then gets dismissed — they said two seconds ago
that it was right. The moment worth interrupting is months later, a different
person, an unrelated investigation, when the assistant holds both the recorded
constraint and a document that says the opposite: **the moment nobody knows both
statements exist.**

Detecting is not settling. The row is opened by whoever noticed — including the
assistant mid-answer — and a human decides which side loses.
"""

from __future__ import annotations

import sqlite3

import pytest

from opspilot.memory import RESOLUTIONS, MemoryConflictStore, MemoryStore


@pytest.fixture
def conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


@pytest.fixture
def store(conn: sqlite3.Connection) -> MemoryConflictStore:
    MemoryStore(conn)  # the FK target
    return MemoryConflictStore(conn)


def _entry(conn: sqlite3.Connection) -> str:
    return (
        MemoryStore(conn)
        .admit(
            statement="Never restart the ESXi cluster on a Tuesday evening",
            reason="finance runs its month-end batch",
            actor="user:alice",
            scope="dc-1",
        )
        .id
    )


class TestOpening:
    def test_a_conflict_starts_open(self, store: MemoryConflictStore, conn) -> None:
        c = store.open_conflict(
            memory_id=_entry(conn), chunk_id="chk_1111aaaa", note="the runbook says Tuesday is fine"
        )
        assert c.is_open and c.status == "open"
        assert store.count_open() == 1

    def test_the_same_pair_does_not_pile_up(self, store: MemoryConflictStore, conn) -> None:
        """The same answer is composed many times; a fresh row each turn buries the one to settle."""
        mem = _entry(conn)
        first = store.open_conflict(memory_id=mem, chunk_id="chk_1111aaaa", note="disagrees")
        again = store.open_conflict(memory_id=mem, chunk_id="chk_1111aaaa", note="disagrees again")
        assert again.id == first.id
        assert store.count_open() == 1

    def test_a_note_is_required(self, store: MemoryConflictStore, conn) -> None:
        with pytest.raises(ValueError, match="note is required"):
            store.open_conflict(memory_id=_entry(conn), chunk_id="chk_1111aaaa", note="  ")

    def test_it_records_where_it_was_noticed(self, store: MemoryConflictStore, conn) -> None:
        c = store.open_conflict(
            memory_id=_entry(conn),
            chunk_id="chk_1111aaaa",
            note="disagrees",
            detected_in="con_abcd1234/msg_1234abcd",
        )
        assert c.detected_in == "con_abcd1234/msg_1234abcd"


class TestSettling:
    @pytest.mark.parametrize("resolution", RESOLUTIONS)
    def test_each_outcome_settles_it(self, store: MemoryConflictStore, conn, resolution) -> None:
        c = store.open_conflict(memory_id=_entry(conn), chunk_id="chk_1111aaaa", note="disagrees")
        store.resolve(c.id, resolution=resolution, resolved_by="user:bob", note="checked it")
        assert store.count_open() == 0
        settled = store.list_conflicts(status=resolution)
        assert settled and settled[0].resolved_by == "user:bob"
        assert settled[0].resolution_note == "checked it"

    def test_merged_is_not_available(self, store: MemoryConflictStore, conn) -> None:
        """Merging would mean editing an entry in place; entries are superseded by appending."""
        assert "merged" not in RESOLUTIONS
        c = store.open_conflict(memory_id=_entry(conn), chunk_id="chk_1111aaaa", note="disagrees")
        with pytest.raises(ValueError, match="resolution must be one of"):
            store.resolve(c.id, resolution="merged", resolved_by="user:bob")  # type: ignore[arg-type]

    def test_the_resolver_is_required(self, store: MemoryConflictStore, conn) -> None:
        c = store.open_conflict(memory_id=_entry(conn), chunk_id="chk_1111aaaa", note="disagrees")
        with pytest.raises(ValueError, match="resolved_by is required"):
            store.resolve(c.id, resolution="dismissed", resolved_by="  ")

    def test_settling_twice_raises(self, store: MemoryConflictStore, conn) -> None:
        c = store.open_conflict(memory_id=_entry(conn), chunk_id="chk_1111aaaa", note="disagrees")
        store.resolve(c.id, resolution="dismissed", resolved_by="user:bob")
        with pytest.raises(KeyError):
            store.resolve(c.id, resolution="dismissed", resolved_by="user:bob")

    def test_a_settled_pair_can_be_raised_again(self, store: MemoryConflictStore, conn) -> None:
        """A resolution is about two things at a point in time, not a standing preference."""
        mem = _entry(conn)
        first = store.open_conflict(memory_id=mem, chunk_id="chk_1111aaaa", note="disagrees")
        store.resolve(first.id, resolution="dismissed", resolved_by="user:bob")
        again = store.open_conflict(memory_id=mem, chunk_id="chk_1111aaaa", note="still disagrees")
        assert again.id != first.id and again.is_open


class TestChatWiring:
    def test_the_tool_is_offered_only_when_memory_is_present(self) -> None:
        """A tool for a section of the prompt that is not there is one the model misuses."""
        from opspilot.orchestrator.chat_agent import _REPORT_CONFLICT_TOOL

        required = _REPORT_CONFLICT_TOOL.parameters["required"]
        assert set(required) == {"memory_id", "chunk_id", "note"}

    def test_the_tool_says_reporting_is_not_settling(self) -> None:
        from opspilot.orchestrator.chat_agent import _REPORT_CONFLICT_TOOL

        assert "does not settle" in _REPORT_CONFLICT_TOOL.description
