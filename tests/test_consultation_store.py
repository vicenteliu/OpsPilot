"""Consultation — cheap, private, short-lived, and pinned when something cites it.

ADR-0032 buys "cheap" with two properties, and both are easy to erode: it is
visible to its author and admins only, and it is swept after 90 days because it
collects pasted logs and configs that never passed a Work item's redaction.

The exception is what these mostly pin. A Consultation cited permanently — by a
Session it escalated into, or by a Memory entry admitted from it — is pinned, or
the citation points at something the sweep deleted and survives in name only.
"""

from __future__ import annotations

import sqlite3

import pytest

from opspilot.consultation import Consultation, ConsultationStore, pin_to_memory
from opspilot.memory import AdmissionError, MemoryStore


@pytest.fixture
def conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


@pytest.fixture
def store(conn: sqlite3.Connection) -> ConsultationStore:
    return ConsultationStore(conn)


@pytest.fixture
def memory(conn: sqlite3.Connection) -> MemoryStore:
    return MemoryStore(conn)


def _with_turns(store: ConsultationStore, author: str = "alice") -> Consultation:
    con = store.start(author=author, title="VPN auth failures")
    store.append(con.id, role="user", content="Half the office cannot connect")
    store.append(con.id, role="assistant", content="Check the RADIUS pool first")
    return con


class TestConversation:
    def test_turns_keep_their_order(self, store: ConsultationStore) -> None:
        con = _with_turns(store)
        seqs = [(m.seq, m.role) for m in store.messages(con.id)]
        assert seqs == [(0, "user"), (1, "assistant")]

    def test_appending_touches_the_consultation(self, store: ConsultationStore) -> None:
        con = store.start(author="alice")
        store.append(con.id, role="user", content="hello")
        after = store.get(con.id)
        assert after is not None and after.updated_at >= con.created_at

    def test_author_is_required(self, store: ConsultationStore) -> None:
        with pytest.raises(ValueError, match="author is required"):
            store.start(author="  ")

    def test_appending_to_an_unknown_consultation_raises(self, store: ConsultationStore) -> None:
        with pytest.raises(KeyError):
            store.append("con_deadbeef", role="user", content="hi")


class TestVisibility:
    def test_the_author_sees_it_and_a_colleague_does_not(self, store: ConsultationStore) -> None:
        con = _with_turns(store, author="alice")
        assert con.visible_to(name="alice", role="operator")
        assert not con.visible_to(name="bob", role="operator")

    def test_an_admin_sees_everything(self, store: ConsultationStore) -> None:
        con = _with_turns(store, author="alice")
        assert con.visible_to(name="admin", role="admin")

    def test_listing_is_scoped_to_the_caller(self, store: ConsultationStore) -> None:
        _with_turns(store, author="alice")
        _with_turns(store, author="bob")
        assert len(store.list_for(name="alice", role="operator")) == 1
        assert len(store.list_for(name="admin", role="admin")) == 2


class TestRetention:
    def test_an_idle_consultation_is_swept(self, store: ConsultationStore) -> None:
        con = _with_turns(store)
        assert store.purge(now="2027-01-01T00:00:00Z") == [con.id]
        assert store.get(con.id) is None
        assert store.messages(con.id) == []

    def test_a_recent_one_is_not(self, store: ConsultationStore) -> None:
        con = _with_turns(store)
        assert store.purge() == []
        assert store.get(con.id) is not None

    def test_an_escalated_one_is_never_swept(self, store: ConsultationStore) -> None:
        """The Session's trace is permanent; its back-reference must not dangle."""
        con = _with_turns(store)
        store.escalate(con.id, session_id="sess_01ABC")
        assert store.purge(now="2030-01-01T00:00:00Z") == []
        after = store.get(con.id)
        assert after is not None and after.is_pinned and after.session_id == "sess_01ABC"

    def test_a_pinned_one_cannot_be_deleted_by_hand_either(self, store: ConsultationStore) -> None:
        con = _with_turns(store)
        store.escalate(con.id, session_id="sess_01ABC")
        with pytest.raises(ValueError, match="pinned"):
            store.delete(con.id)

    def test_an_unpinned_one_can_be_deleted_by_hand(self, store: ConsultationStore) -> None:
        con = _with_turns(store)
        store.delete(con.id)
        assert store.get(con.id) is None


class TestPinToMemory:
    def test_pinning_admits_the_entry_and_records_its_source(
        self, store: ConsultationStore, memory: MemoryStore
    ) -> None:
        con = _with_turns(store)
        msg = store.messages(con.id)[1]
        entry = pin_to_memory(
            store,
            memory,
            message_id=msg.id,
            statement="The RADIUS pool is load-balanced across three nodes",
            reason="explains why only some users fail at once",
            actor="user:alice",
            scope="dc-1",
        )
        assert entry.source_ref == f"{con.id}/{msg.id}"
        assert entry.actor == "user:alice"
        assert entry.scope == "dc-1"

    def test_pinning_protects_the_consultation_from_the_sweep(
        self, store: ConsultationStore, memory: MemoryStore
    ) -> None:
        """The entry cites this conversation permanently; the citation must resolve."""
        con = _with_turns(store)
        msg = store.messages(con.id)[1]
        pin_to_memory(
            store, memory, message_id=msg.id, reason="worth remembering", actor="user:alice"
        )
        after = store.get(con.id)
        assert after is not None and after.pinned_reason == "memory_source"
        assert store.purge(now="2030-01-01T00:00:00Z") == []

    def test_the_message_text_is_the_default_statement(
        self, store: ConsultationStore, memory: MemoryStore
    ) -> None:
        con = _with_turns(store)
        msg = store.messages(con.id)[0]
        entry = pin_to_memory(
            store, memory, message_id=msg.id, reason="scope of the outage", actor="user:alice"
        )
        assert entry.statement == "Half the office cannot connect"

    def test_a_missing_reason_admits_nothing_and_pins_nothing(
        self, store: ConsultationStore, memory: MemoryStore
    ) -> None:
        con = _with_turns(store)
        msg = store.messages(con.id)[1]
        with pytest.raises(AdmissionError):
            pin_to_memory(store, memory, message_id=msg.id, reason="", actor="user:alice")
        after = store.get(con.id)
        assert after is not None and not after.is_pinned

    def test_an_unknown_message_raises(self, store: ConsultationStore, memory: MemoryStore) -> None:
        with pytest.raises(KeyError):
            pin_to_memory(store, memory, message_id="msg_deadbeef", reason="x", actor="user:alice")


def test_shares_the_connection_lock(conn: sqlite3.Connection) -> None:
    from opspilot.dblock import lock_for

    assert ConsultationStore(conn)._lock is lock_for(conn)
