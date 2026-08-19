"""Removing a KB document (#156).

Ingest is the one KB operation a user is invited to run repeatedly against their
own directories, so ingesting the wrong folder — or one with secrets in it — is
an ordinary mistake, and until now a permanent one.

That case is what makes this a **hard** delete rather than a retirement: a soft
delete leaves the content in the database, which does not answer *"we ingested
something we should not have"*.

Corrections and settled conflicts about the document go with it, and that is not
in tension with #194. That change stopped a re-ingest *accidentally* destroying a
judgement nobody asked to delete. This is somebody deliberately saying the
content should not be here, and a correction quotes the content it replaced.

What survives is a `kb_deletions` row: what went, who decided, and why — quoting
nothing. The Asset event precedent, where the log outlives the row.

The two traps #156 named were real when it was filed and are closed now
(`foreign_keys` is ON in `_PRAGMAS`, and the cascade fires the FTS trigger).
They are pinned here because a closed trap can reopen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite

DOC = "doc_1111aaaa"
OTHER = "doc_2222bbbb"


def _doc(doc_id: str, path: str) -> dict[str, Any]:
    return {
        "id": doc_id,
        "source_path": path,
        "title": f"title of {doc_id}",
        "classification": "internal",
        "content_hash": "sha256:" + "a" * 64,
        "ingested_at": "2026-08-18T10:00:00Z",
        "language": "en",
        "tags": [],
        "namespace": "ns",
        "chunk_strategy": "headings_then_size",
        "chunk_count": 1,
        "embedding_model": "m",
        "embedding_dim": 8,
        "redaction_passed": True,
    }


def _chunk(cid: str, doc_id: str, seq: int, content: str) -> dict[str, Any]:
    return {
        "id": cid,
        "document_id": doc_id,
        "seq": seq,
        "content": content,
        "content_hash": "sha256:" + "b" * 64,
        "char_start": 0,
        "char_end": 5,
        "line_start": 1,
        "line_end": 2,
        "heading_path": [],
        "anchor": "#a",
        "token_count": 2,
        "embedding_model": "m",
        "vector_id": f"vec_{cid[-8:]}",
        "namespace": "ns",
        "classification": "internal",
        "language": "en",
        "tags": [],
        "redaction_passed": True,
    }


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    s = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    s.upsert_document(_doc(DOC, "secrets/leaked.md"))
    s.upsert_chunks([_chunk("chk_0000aaaa", DOC, 0, "Zarquon is the secret token")])
    s.upsert_document(_doc(OTHER, "fine/other.md"))
    s.upsert_chunks([_chunk("chk_0000cccc", OTHER, 0, "Blorptech is unrelated")])
    return s


def _delete(store: SqliteStore) -> dict[str, Any]:
    return store.delete_document(DOC, actor="user:alice", reason="ingested the wrong folder")


class TestRemoval:
    def test_the_document_and_its_chunks_go(self, store: SqliteStore) -> None:
        _delete(store)
        assert store.get_document(DOC) is None
        assert store.get_chunks_by_document_id(DOC) == []

    def test_keyword_search_stops_returning_it(self, store: SqliteStore) -> None:
        """Trap 2 in #156: FTS is only kept in step by a trigger on kb_chunks."""
        assert store.fts_search("Zarquon", top_k=5)
        _delete(store)
        assert store.fts_search("Zarquon", top_k=5) == []

    def test_the_caller_is_told_which_vectors_to_clear(self, store: SqliteStore) -> None:
        """This method touches SQLite only; LanceDB is not cascaded by anything."""
        assert _delete(store)["vector_ids"] == ["vec_0000aaaa"]

    def test_another_document_is_untouched(self, store: SqliteStore) -> None:
        _delete(store)
        assert store.get_document(OTHER) is not None
        assert store.fts_search("Blorptech", top_k=5)


class TestDecisionsAboutIt:
    def test_a_correction_quoting_the_content_goes_too(self, store: SqliteStore) -> None:
        """A deliberate purge, unlike the accidental destruction #194 stopped."""
        store.add_correction("chk_0000aaaa", corrected_by="a", reason="r", new_content="x")
        report = _delete(store)
        assert report["corrections_removed"] == 1
        assert store.list_corrections(chunk_id="chk_0000aaaa") == []

    def test_a_correction_on_another_document_survives(self, store: SqliteStore) -> None:
        store.add_correction("chk_0000cccc", corrected_by="a", reason="r", new_content="x")
        _delete(store)
        assert len(store.list_corrections(chunk_id="chk_0000cccc")) == 1


class TestTheRecordOfTheRemoval:
    def test_it_says_what_went_and_who_decided(self, store: SqliteStore) -> None:
        _delete(store)
        rows = store.list_deletions()
        assert len(rows) == 1
        assert rows[0]["document_id"] == DOC
        assert rows[0]["actor"] == "user:alice"
        assert rows[0]["reason"] == "ingested the wrong folder"
        assert rows[0]["chunks_removed"] == 1

    def test_it_quotes_no_content(self, store: SqliteStore) -> None:
        """Deleting is how a leak is answered; the log must not re-create it."""
        _delete(store)
        assert "Zarquon" not in str(store.list_deletions()[0])

    def test_an_unexplained_deletion_is_refused(self, store: SqliteStore) -> None:
        with pytest.raises(ValueError, match="reason is required"):
            store.delete_document(DOC, actor="user:alice", reason="  ")
        assert store.get_document(DOC) is not None

    def test_an_unowned_deletion_is_refused(self, store: SqliteStore) -> None:
        with pytest.raises(ValueError, match="actor is required"):
            store.delete_document(DOC, actor="", reason="because")
        assert store.get_document(DOC) is not None

    def test_deleting_something_absent_raises(self, store: SqliteStore) -> None:
        with pytest.raises(KeyError):
            store.delete_document("doc_9999ffff", actor="a", reason="r")


def test_foreign_keys_are_on(tmp_path: Path) -> None:
    """Trap 1 in #156: with the pragma off the cascade silently does not happen."""
    conn = init_sqlite(tmp_path / "kb.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
