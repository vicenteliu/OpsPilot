"""A human decision about trustworthiness outlives the chunk it was about (#194).

`CONTEXT.md` names the two together and says exactly what they are:

    Both a Resolution and a Correction record who acted, taken from the caller's
    identity and never from what the caller claims — … these are the decisions
    about which knowledge is trustworthy, so the one thing that must not be
    self-reported is who decided.

The system took great care that *who decided* could not be faked, and then a
re-ingest deleted the record: both tables hung off `kb_chunks` with
`ON DELETE CASCADE`, so fixing a source file properly destroyed the correction —
including the `old_content` the record exists to keep — and any conflict somebody
had already settled.

The distinction the cascade could not make, and this does:

* an **open** conflict about text that no longer exists is spent — nobody should
  be asked to settle a contradiction that is not there any more, and it still
  goes;
* a **settled** one is a judgement with an actor and a reason, and ADR-0029 rests
  entirely on that reason surviving to be re-examined.

The precedent is the Asset event: deleting an Asset removes the row, not its log.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite

DOC = "doc_1111aaaa"
STALE = "chk_0000aaaa"
KEPT = "chk_0000bbbb"


def _doc() -> dict[str, Any]:
    return {
        "id": DOC,
        "source_path": "x/s.md",
        "title": "t",
        "classification": "internal",
        "content_hash": "sha256:" + "a" * 64,
        "ingested_at": "2026-08-18T10:00:00Z",
        "language": "en",
        "tags": [],
        "namespace": "ns",
        "chunk_strategy": "headings_then_size",
        "chunk_count": 2,
        "embedding_model": "m",
        "embedding_dim": 8,
        "redaction_passed": True,
    }


def _chunk(cid: str, seq: int) -> dict[str, Any]:
    return {
        "id": cid,
        "document_id": DOC,
        "seq": seq,
        "content": f"text {seq}",
        "content_hash": "sha256:" + "b" * 64,
        "char_start": 0,
        "char_end": 5,
        "line_start": 1,
        "line_end": 2,
        "heading_path": [],
        "anchor": "#a",
        "token_count": 2,
        "embedding_model": "m",
        "vector_id": f"vec_{seq:08d}",
        "namespace": "ns",
        "classification": "internal",
        "language": "en",
        "tags": [],
        "redaction_passed": True,
    }


def _conflict(cid: str) -> dict[str, Any]:
    return {
        "id": cid,
        "chunk_a_id": STALE,
        "chunk_b_id": KEPT,
        "doc_a_id": DOC,
        "doc_b_id": DOC,
        "conflict_type": "direct_contradiction",
        "similarity": 0.9,
        "detected_at": "2026-08-18T10:00:00Z",
        "status": "open",
    }


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    s = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    s.upsert_document(_doc())
    s.upsert_chunks([_chunk(STALE, 0), _chunk(KEPT, 1)])
    return s


def _reingest(store: SqliteStore) -> None:
    """What fixing the source file does: the stale chunk's id no longer exists."""
    store.delete_chunks_not_in(DOC, [KEPT])


class TestCorrections:
    def test_a_correction_survives_the_fix_it_stood_in_for(self, store: SqliteStore) -> None:
        store.add_correction(STALE, corrected_by="user:alice", reason="wrong", new_content="right")
        _reingest(store)
        rows = store.list_corrections(chunk_id=STALE)
        assert rows, "the correction was destroyed by the very fix it stood in for"
        assert rows[0]["corrected_by"] == "user:alice"
        assert rows[0]["reason"] == "wrong"

    def test_the_old_content_is_still_there(self, store: SqliteStore) -> None:
        """CONTEXT.md: 'the old content is kept on the correction record'."""
        store.add_correction(STALE, corrected_by="user:alice", reason="wrong", new_content="right")
        _reingest(store)
        assert store.list_corrections(chunk_id=STALE)[0]["old_content"] == "text 0"

    def test_an_orphan_still_names_what_it_was_about(self, store: SqliteStore) -> None:
        store.add_correction(STALE, corrected_by="user:alice", reason="wrong", new_content="right")
        _reingest(store)
        assert store.list_corrections(chunk_id=STALE)[0]["document_id"] == DOC

    def test_an_orphan_is_inert(self, store: SqliteStore) -> None:
        """Reads are by live chunk id, so a decision about a gone chunk never matches."""
        store.add_correction(STALE, corrected_by="user:alice", reason="wrong", new_content="right")
        _reingest(store)
        assert store.get_corrected_chunk_ids([KEPT]) == set()


class TestConflicts:
    def test_a_settled_conflict_survives(self, store: SqliteStore) -> None:
        store.upsert_conflict(_conflict("conf_11112222"))
        store.update_conflict_status(
            "conf_11112222",
            status="a_wins",
            resolved_by="user:bob",
            resolved_at="2026-08-18T11:00:00Z",
            resolution_note="reproduced on the array",
        )
        _reingest(store)
        settled = store.get_conflict("conf_11112222")
        assert settled is not None, "a human's judgement was deleted with the text"
        assert settled["resolved_by"] == "user:bob"
        assert settled["resolution_note"] == "reproduced on the array"

    def test_an_open_conflict_still_goes(self, store: SqliteStore) -> None:
        """Correct, not collateral: nobody should settle a contradiction that is gone."""
        store.upsert_conflict(_conflict("conf_33334444"))
        _reingest(store)
        assert store.get_conflict("conf_33334444") is None

    def test_an_untouched_conflict_is_left_alone(self, store: SqliteStore) -> None:
        store.upsert_chunks([_chunk("chk_0000cccc", 2)])
        store.upsert_conflict(
            {**_conflict("conf_55556666"), "chunk_a_id": KEPT, "chunk_b_id": "chk_0000cccc"}
        )
        store.delete_chunks_not_in(DOC, [KEPT, "chk_0000cccc"])
        assert store.get_conflict("conf_55556666") is not None


class TestMigration:
    def test_an_existing_database_loses_the_cascade(self, tmp_path: Path) -> None:
        """The rebuild has to run on databases created before this change.

        The "old" database is a real one with the cascade put back, rather than a
        hand-written minimal schema — a fixture that does not match production is
        a migration test that proves nothing.
        """
        import sqlite3

        db = tmp_path / "old.db"
        init_sqlite(db).close()

        raw = sqlite3.connect(db)
        raw.executescript(
            "PRAGMA foreign_keys=OFF;"
            "ALTER TABLE kb_corrections RENAME TO kb_corrections_pre194;"
            "CREATE TABLE kb_corrections ("
            " id TEXT PRIMARY KEY,"
            " chunk_id TEXT NOT NULL REFERENCES kb_chunks(id) ON DELETE CASCADE,"
            " corrected_by TEXT NOT NULL, reason TEXT NOT NULL,"
            " old_content TEXT NOT NULL, new_content TEXT NOT NULL,"
            " created_at TEXT NOT NULL);"
            "DROP TABLE kb_corrections_pre194;"
        )
        raw.execute(
            "INSERT INTO kb_corrections VALUES "
            "('corr_0000aaaa','chk_0000aaaa','alice','wrong','old text','new text','t')"
        )
        raw.commit()
        assert any(
            str(r[2]) == "kb_chunks" for r in raw.execute("PRAGMA foreign_key_list(kb_corrections)")
        ), "the fixture did not actually restore the cascade"
        raw.close()

        migrated = init_sqlite(db)
        fks = migrated.execute("PRAGMA foreign_key_list(kb_corrections)").fetchall()
        assert not any(str(r[2]) == "kb_chunks" for r in fks), "the cascade survived the migration"
        rows = migrated.execute(
            "SELECT id, corrected_by, old_content FROM kb_corrections"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("corr_0000aaaa", "alice", "old text")], (
            "the migration lost data"
        )

    def test_running_it_twice_changes_nothing(self, tmp_path: Path) -> None:
        db = tmp_path / "kb.db"
        init_sqlite(db).close()
        conn = init_sqlite(db)
        assert conn.execute("SELECT COUNT(*) FROM kb_corrections").fetchone()[0] == 0
