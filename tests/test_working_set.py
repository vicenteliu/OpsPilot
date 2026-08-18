"""Working set — one open problem per person, and a fallback that says so.

ADR-0032 settled that a Working set must close, and that the close action is the
one nobody performs: the moment a problem is solved is the moment you move on.
So the fallback is unconditional — and it **announces itself**, because a set
that expired silently leaves the operator misreading why the assistant lost the
thread.

It is also what makes anchored Memory reachable from a chat turn at all. Without
one, a turn sees the global constraints and nothing else.
"""

from __future__ import annotations

import sqlite3

import pytest

from opspilot.consultation import IDLE_DAYS, WorkingSetStore
from opspilot.memory import MemoryStore
from opspilot.orchestrator.chat_agent import turn_anchors


@pytest.fixture
def conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


@pytest.fixture
def store(conn: sqlite3.Connection) -> WorkingSetStore:
    return WorkingSetStore(conn)


class TestOpenAndClose:
    def test_opening_records_the_problem_and_its_address(self, store: WorkingSetStore) -> None:
        ws = store.open(owner="alice", title="dc-1 storage latency", scope="dc-1")
        assert ws.is_open and ws.scope == "dc-1"
        assert store.current("alice") is not None

    def test_a_title_is_required(self, store: WorkingSetStore) -> None:
        with pytest.raises(ValueError, match="title is required"):
            store.open(owner="alice", title="  ")

    def test_only_one_is_open_per_person(self, store: WorkingSetStore) -> None:
        """Two would put back the question of which one anchors a turn."""
        first = store.open(owner="alice", title="first", scope="dc-1")
        second = store.open(owner="alice", title="second", scope="dc-2")
        current = store.current("alice")
        assert current is not None and current.id == second.id
        closed = [w for w in store.history("alice") if w.id == first.id][0]
        assert not closed.is_open and closed.closed_reason == "manual"

    def test_switching_deliberately_announces_nothing(self, store: WorkingSetStore) -> None:
        store.open(owner="alice", title="first")
        store.open(owner="alice", title="second")
        assert store.take_announcement("alice") is None

    def test_two_people_each_get_one(self, store: WorkingSetStore) -> None:
        store.open(owner="alice", title="alice's problem")
        store.open(owner="bob", title="bob's problem")
        for who in ("alice", "bob"):
            assert store.current(who) is not None


class TestFallback:
    def test_an_idle_set_is_closed(self, store: WorkingSetStore) -> None:
        store.open(owner="alice", title="dc-1 storage latency")
        closed = store.sweep(now="2027-01-01T00:00:00Z")
        assert [w.title for w in closed] == ["dc-1 storage latency"]
        assert store.current("alice") is None

    def test_an_active_set_survives(self, store: WorkingSetStore) -> None:
        store.open(owner="alice", title="still on it")
        assert store.sweep() == []
        assert store.current("alice") is not None

    def test_activity_resets_the_clock(self, store: WorkingSetStore) -> None:
        """The fallback measures silence, not age."""
        store.open(owner="alice", title="long investigation")
        store.touch("alice")
        assert store.sweep() == []

    def test_the_closure_is_announced_once(self, store: WorkingSetStore) -> None:
        store.open(owner="alice", title="dc-1 storage latency")
        store.sweep(now="2027-01-01T00:00:00Z")
        first = store.take_announcement("alice")
        assert first is not None
        assert "dc-1 storage latency" in first and str(IDLE_DAYS) in first
        assert store.take_announcement("alice") is None

    def test_nothing_to_announce_when_nothing_expired(self, store: WorkingSetStore) -> None:
        store.open(owner="alice", title="fine")
        assert store.take_announcement("alice") is None

    def test_a_manual_close_is_not_announced(self, store: WorkingSetStore) -> None:
        ws = store.open(owner="alice", title="solved it")
        store.close(ws.id)
        assert store.take_announcement("alice") is None


class TestAnchoring:
    def test_the_working_set_supplies_the_turn_anchors(self, conn: sqlite3.Connection) -> None:
        store = WorkingSetStore(conn)
        store.open(owner="alice", title="dc-1 storage latency", scope="dc-1", asset_id="ast_1")

        class _State:
            working_sets = store

        assert turn_anchors(_State(), owner="alice", asset_id=None, scope=None) == ("ast_1", "dc-1")

    def test_an_explicit_anchor_wins(self, conn: sqlite3.Connection) -> None:
        """Asking about another site is not overruled by what you are working on."""
        store = WorkingSetStore(conn)
        store.open(owner="alice", title="dc-1 work", scope="dc-1")

        class _State:
            working_sets = store

        assert turn_anchors(_State(), owner="alice", asset_id=None, scope="dc-2") == (None, "dc-2")

    def test_no_working_set_means_globals_only(self, conn: sqlite3.Connection) -> None:
        class _State:
            working_sets = WorkingSetStore(conn)

        assert turn_anchors(_State(), owner="alice", asset_id=None, scope=None) == (None, None)

    def test_anchored_memory_becomes_reachable(self, conn: sqlite3.Connection) -> None:
        """The point of the whole thing: without a set, anchored entries never inject."""
        from opspilot.memory import memory_block

        memory = MemoryStore(conn)
        working = WorkingSetStore(conn)
        memory.admit(
            statement="Never restart the ESXi cluster on a Tuesday evening",
            reason="finance runs its month-end batch",
            actor="user:alice",
            scope="dc-1",
        )
        assert memory_block(memory) == ""  # no anchor, nothing anchored applies

        working.open(owner="alice", title="dc-1 reboot window", scope="dc-1")

        class _State:
            working_sets = working

        asset_id, scope = turn_anchors(_State(), owner="alice", asset_id=None, scope=None)
        assert "Tuesday evening" in memory_block(memory, asset_id=asset_id, scope=scope)
