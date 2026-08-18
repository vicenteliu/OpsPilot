"""Memory — the second owned domain (ADR-0031, revised by ADR-0035).

What these pin is the part that is easy to erode: an entry is *admitted* by a
person who supplied a reason, it is superseded by appending rather than editing,
a stale review date changes a label and never withholds the entry, and un-anchored
constraints are capped so "global" cannot quietly become "everything".
"""

from __future__ import annotations

import sqlite3

import pytest

from opspilot.memory import GLOBAL_ENTRY_CAP, AdmissionError, MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore(sqlite3.connect(":memory:"))


def _admit(store: MemoryStore, statement: str = "No ESXi restarts Tuesday evening", **kw):
    kw.setdefault("reason", "finance runs its batch then")
    kw.setdefault("actor", "user:alice")
    return store.admit(statement=statement, **kw)


class TestAdmission:
    def test_an_entry_records_who_and_when(self, store: MemoryStore) -> None:
        entry = _admit(store)
        assert entry.id.startswith("mem_") and len(entry.id) == 12
        assert entry.actor == "user:alice"
        assert entry.created_at.endswith("Z")
        assert entry.is_live and entry.is_global

    def test_reason_is_required(self, store: MemoryStore) -> None:
        """Without it, nobody can judge the entry when its review date arrives."""
        with pytest.raises(AdmissionError, match="reason is required"):
            store.admit(statement="something", reason="   ", actor="user:alice")

    def test_actor_is_required(self, store: MemoryStore) -> None:
        with pytest.raises(AdmissionError, match="actor is required"):
            store.admit(statement="something", reason="because", actor="")

    def test_ids_do_not_collide_for_identical_statements(self, store: MemoryStore) -> None:
        """Two people writing the same sentence are two facts about the world.

        A content-addressed id would collapse them and destroy the ageing data
        the review dates exist to produce.
        """
        a, b = _admit(store), _admit(store)
        assert a.id != b.id


class TestAnchors:
    def test_an_anchored_entry_applies_only_at_its_address(self, store: MemoryStore) -> None:
        _admit(store, "Vendor manages the firewall here", scope="site-b")
        assert store.applicable(scope="site-b")
        assert store.applicable(scope="site-a") == []

    def test_a_global_entry_applies_everywhere(self, store: MemoryStore) -> None:
        _admit(store, "No production change on a Friday")
        assert len(store.applicable(scope="site-a")) == 1
        assert len(store.applicable()) == 1

    def test_asset_and_scope_anchors_both_match(self, store: MemoryStore) -> None:
        _admit(store, "This one reboots slowly", asset_id="ast_1")
        _admit(store, "Vendor-managed site", scope="site-b")
        hits = {e.statement for e in store.applicable(asset_id="ast_1", scope="site-b")}
        assert hits == {"This one reboots slowly", "Vendor-managed site"}

    def test_scopes_lists_what_exists_for_pick_or_create(self, store: MemoryStore) -> None:
        _admit(store, "a", scope="site-b")
        _admit(store, "b", scope="site-a")
        _admit(store, "c", scope="site-a")
        assert store.scopes() == ["site-a", "site-b"]


class TestGlobalCap:
    def test_overflow_forces_an_anchor_or_an_archive(self, store: MemoryStore) -> None:
        for i in range(GLOBAL_ENTRY_CAP):
            _admit(store, f"global constraint {i}")
        with pytest.raises(AdmissionError, match="global entries already"):
            _admit(store, "one too many")
        # An anchor is always a way out — the cap is about *global* entries.
        assert _admit(store, "one too many", scope="site-a").is_live

    def test_archiving_frees_a_slot(self, store: MemoryStore) -> None:
        entries = [_admit(store, f"global {i}") for i in range(GLOBAL_ENTRY_CAP)]
        store.archive(entries[0].id)
        assert _admit(store, "now it fits").is_live


class TestSupersede:
    def test_superseding_appends_and_keeps_the_old_entry(self, store: MemoryStore) -> None:
        """'We recorded it wrong' and 'the world changed' must stay apart."""
        old = _admit(store, "No ESXi restarts Tuesday evening", scope="dc-1")
        new = store.supersede(
            old.id,
            statement="No ESXi restarts Thursday evening",
            reason="finance moved the batch",
            actor="user:bob",
        )
        was = store.get(old.id)
        assert was is not None
        assert was.statement == "No ESXi restarts Tuesday evening"  # not edited
        assert was.superseded_by == new.id and was.superseded_at is not None
        assert not was.is_live
        assert new.scope == "dc-1"  # anchors carry over

    def test_only_the_replacement_is_applicable(self, store: MemoryStore) -> None:
        old = _admit(store, "old rule", scope="dc-1")
        store.supersede(old.id, statement="new rule", reason="changed", actor="user:bob")
        assert [e.statement for e in store.applicable(scope="dc-1")] == ["new rule"]

    def test_a_superseded_entry_cannot_be_superseded_again(self, store: MemoryStore) -> None:
        old = _admit(store, "old rule")
        store.supersede(old.id, statement="new rule", reason="changed", actor="user:bob")
        with pytest.raises(AdmissionError, match="already superseded"):
            store.supersede(old.id, statement="newer", reason="again", actor="user:bob")

    def test_history_survives_so_you_can_see_how_long_it_held(self, store: MemoryStore) -> None:
        old = _admit(store, "old rule", review_after="2027-01-01T00:00:00Z")
        store.supersede(old.id, statement="new rule", reason="changed", actor="user:bob")
        retired = [e for e in store.list_entries(include_retired=True) if e.id == old.id]
        assert retired and retired[0].review_after == "2027-01-01T00:00:00Z"


class TestReviewDate:
    def test_overdue_is_a_label_not_a_withholding(self, store: MemoryStore) -> None:
        """Hard expiry was rejected: it drops a correct constraint at the worst moment."""
        entry = _admit(store, "still true", scope="dc-1", review_after="2020-01-01T00:00:00Z")
        assert entry.review_overdue_at("2026-08-18T00:00:00Z")
        assert [e.id for e in store.applicable(scope="dc-1")] == [entry.id]

    def test_no_review_date_is_never_overdue(self, store: MemoryStore) -> None:
        assert not _admit(store).review_overdue_at("2099-01-01T00:00:00Z")


def test_shares_the_connection_lock_with_the_other_stores() -> None:
    """Four stores already drive one connection; a fifth must join the same lock."""
    from opspilot.dblock import lock_for

    conn = sqlite3.connect(":memory:")
    store = MemoryStore(conn)
    assert store._lock is lock_for(conn)
