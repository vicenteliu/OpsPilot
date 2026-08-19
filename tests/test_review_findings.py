"""Regressions from a review of the Memory / Consultation / actions batch.

Each of these was a real defect on `main`, and the first is the one that matters:
a message id is globally unique but says nothing about who may read it, so a
route that checked one Consultation and then resolved a message from another
handed private text to anybody with an operator role.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from opspilot.consultation import ConsultationStore, pin_to_memory
from opspilot.memory import GLOBAL_ENTRY_CAP, MemoryStore
from opspilot.portability.bundle import _safe_extract  # noqa: PLC2701


@pytest.fixture
def conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


class TestPinCannotReachAnotherConversation:
    def test_a_message_from_someone_elses_consultation_is_refused(self, conn) -> None:
        """Naming your own Consultation must not admit a message out of another.

        Before the fix this returned the victim's text as a team-visible Memory
        entry, echoed it in the response, and pinned their Consultation against
        the retention sweep.
        """
        cs, ms = ConsultationStore(conn), MemoryStore(conn)
        victim = cs.start(author="bob", title="bob's private chat")
        secret = cs.append(victim.id, role="user", content="SECRET: laptop password is hunter2")
        mine = cs.start(author="alice", title="alice's chat")

        with pytest.raises(KeyError, match="is not in"):
            pin_to_memory(
                cs,
                ms,
                message_id=secret.id,
                consultation_id=mine.id,
                reason="looks useful",
                actor="user:alice",
            )
        assert ms.list_entries() == []
        assert not cs.get(victim.id).is_pinned

    def test_a_message_from_your_own_consultation_still_works(self, conn) -> None:
        cs, ms = ConsultationStore(conn), MemoryStore(conn)
        mine = cs.start(author="alice", title="alice's chat")
        msg = cs.append(mine.id, role="assistant", content="The RADIUS pool has three nodes")
        entry = pin_to_memory(
            cs, ms, message_id=msg.id, consultation_id=mine.id, reason="r", actor="user:alice"
        )
        assert entry.source_ref == f"{mine.id}/{msg.id}"


class TestSupersedeAtTheCap:
    def test_a_capped_out_global_entry_can_still_be_corrected(self, conn) -> None:
        """Replacing is net-neutral on the count, and the old entry is still live.

        Enforcing the cap here forced archive-then-admit, which loses the
        superseded_by link — the very history that separates "we recorded it
        wrong" from "the world changed".
        """
        store = MemoryStore(conn)
        ids = [
            store.admit(statement=f"g{i}", reason="r", actor="a").id
            for i in range(GLOBAL_ENTRY_CAP)
        ]
        new = store.supersede(ids[0], statement="replacement", reason="changed", actor="b")
        old = store.get(ids[0])
        assert old is not None and old.superseded_by == new.id
        assert len([e for e in store.list_entries() if e.is_global]) == GLOBAL_ENTRY_CAP

    def test_the_cap_still_bites_on_a_fresh_entry(self, conn) -> None:
        from opspilot.memory import AdmissionError

        store = MemoryStore(conn)
        for i in range(GLOBAL_ENTRY_CAP):
            store.admit(statement=f"g{i}", reason="r", actor="a")
        with pytest.raises(AdmissionError, match="global entries already"):
            store.admit(statement="one too many", reason="r", actor="a")


class TestSettingsStoreIsSerialised:
    def test_delete_holds_the_connection_lock(self, conn) -> None:
        """It was the one method left outside — and commit() is connection-scoped."""
        from opspilot.dblock import lock_for
        from opspilot.settings_store import SettingsStore

        store = SettingsStore(conn)
        assert store._lock is lock_for(conn)
        store.set("k", "v")
        store.delete("k")
        assert store.get("k") is None


class TestBundleContainment:
    def test_a_sibling_sharing_the_prefix_is_refused(self, tmp_path: Path) -> None:
        """ "/x/import-evil" starts with "/x/import" and is not inside it."""
        import tarfile

        dest = tmp_path / "import"
        dest.mkdir()
        (tmp_path / "payload").write_text("bad", encoding="utf-8")
        archive = tmp_path / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(tmp_path / "payload", arcname="../import-evil/x")
        with tarfile.open(archive, "r:gz") as tar, pytest.raises(ValueError, match="escapes"):
            _safe_extract(tar, dest)
