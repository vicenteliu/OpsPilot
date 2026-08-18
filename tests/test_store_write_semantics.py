"""Write semantics of ``SqliteStore``: what an upsert is allowed to destroy.

Three methods used SQLite conflict-resolution clauses as a convenience, and
each one silently did more than its name promised:

* ``upsert_document``  — ``INSERT OR REPLACE`` deleted the row, cascading to
  ``kb_chunks`` and, through them, to ``kb_conflicts`` and ``kb_corrections``
  (#144, #157).
* ``upsert_chunks``    — ``INSERT OR REPLACE`` deleted each chunk row before
  reinserting it, taking that chunk's conflicts and corrections (#157).
* ``upsert_conflict``  — ``INSERT OR IGNORE`` swallowed CHECK violations, so a
  mistyped ``conflict_type`` wrote nothing and reported success (#143).

The distinction these tests pin down: a **Chunk** is regenerable, a
**Correction** and a **Resolution** are not — they are human decisions about
which knowledge is trustworthy, and an upsert must not discard them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite

DOC_ID = "doc_88a277cf"
CHUNK_A = "chk_aaaa0001"
CHUNK_B = "chk_bbbb0002"
CONFLICT_ID = "conf_00000001"


def _doc(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": DOC_ID,
        "source_path": f"examples/{DOC_ID}/source.md",
        "title": "VPN troubleshooting SOP",
        "classification": "internal",
        "content_hash": "sha256:" + ("a" * 64),
        "version": "1.3.0",
        "ingested_at": "2026-05-01T10:00:00Z",
        "language": "en",
        "tags": ["vpn", "sop"],
        "namespace": "opspilot:public-kb",
        "chunk_strategy": "headings_then_size",
        "chunk_count": 2,
        "embedding_model": "ollama-local/nomic-embed-text@2024-02",
        "embedding_dim": 768,
        "redaction_passed": True,
    }
    base.update(overrides)
    return base


def _chunk(chk_id: str, *, seq: int = 0, content: str = "VPN auth failure") -> dict[str, Any]:
    return {
        "id": chk_id,
        "document_id": DOC_ID,
        "seq": seq,
        "content": content,
        "content_hash": "sha256:" + ("a" * 64),
        "char_start": 0,
        "char_end": len(content),
        "line_start": 1,
        "line_end": 1,
        "heading_path": ["VPN SOP"],
        "anchor": None,
        "token_count": 50,
        "embedding_model": "ollama-local/nomic-embed-text@2024-02",
        "vector_id": f"vec_{chk_id}",
        "metadata": {
            "tags": ["vpn"],
            "namespace": "opspilot:public-kb",
            "classification": "internal",
            "language": "en",
        },
    }


def _conflict(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": CONFLICT_ID,
        "chunk_a_id": CHUNK_A,
        "chunk_b_id": CHUNK_B,
        "doc_a_id": DOC_ID,
        "doc_b_id": DOC_ID,
        "conflict_type": "direct_contradiction",
        "similarity": 0.9,
        "status": "open",
        "detected_at": "2026-07-31T00:00:00Z",
    }
    base.update(overrides)
    return base


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    """A document with two chunks, one correction, and one open conflict."""
    s = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    s.upsert_document(_doc())
    s.upsert_chunks([_chunk(CHUNK_A, seq=0), _chunk(CHUNK_B, seq=1, content="other text")])
    s.add_correction(CHUNK_A, "vicente", "typo in the SOP", "VPN auth failure (corrected)")
    s.upsert_conflict(_conflict())
    return s


def _human_decisions(store: SqliteStore) -> tuple[int, bool]:
    """(corrections on CHUNK_A, the conflict still exists)."""
    return len(store.list_corrections(chunk_id=CHUNK_A)), store.get_conflict(
        CONFLICT_ID
    ) is not None


# ── upsert_document must not touch anything below the document row ──


class TestUpsertDocument:
    def test_unchanged_reupsert_keeps_chunks(self, store: SqliteStore) -> None:
        store.upsert_document(_doc())
        assert store.get_chunk(CHUNK_A) is not None
        assert store.get_chunk(CHUNK_B) is not None

    def test_unchanged_reupsert_keeps_human_decisions(self, store: SqliteStore) -> None:
        assert _human_decisions(store) == (1, True)
        store.upsert_document(_doc())
        assert _human_decisions(store) == (1, True)

    def test_metadata_only_write_keeps_human_decisions(self, store: SqliteStore) -> None:
        """A title backfill is the case #144 warned about: a caller touching
        the document row for its own reasons, silently emptying the document."""
        store.upsert_document(_doc(title="VPN troubleshooting SOP (v2)"))
        assert store.get_document(DOC_ID)["title"] == "VPN troubleshooting SOP (v2)"  # type: ignore[index]
        assert _human_decisions(store) == (1, True)

    def test_still_updates_the_row(self, store: SqliteStore) -> None:
        store.upsert_document(_doc(classification="restricted", version="2.0.0"))
        doc = store.get_document(DOC_ID)
        assert doc is not None
        assert doc["classification"] == "restricted"
        assert doc["version"] == "2.0.0"


# ── upsert_chunks must not discard a chunk's own children ──


class TestUpsertChunks:
    def test_reupserting_the_corrected_chunk_keeps_its_correction(self, store: SqliteStore) -> None:
        store.upsert_chunks([_chunk(CHUNK_A, seq=0)])
        assert _human_decisions(store) == (1, True)

    def test_reupserting_the_other_side_keeps_the_conflict(self, store: SqliteStore) -> None:
        """A conflict is a claim about a *pair* — before #157, re-writing
        either half silently retracted it."""
        store.upsert_chunks([_chunk(CHUNK_B, seq=1, content="other text")])
        assert store.get_conflict(CONFLICT_ID) is not None

    def test_still_updates_content(self, store: SqliteStore) -> None:
        """CHUNK_B carries no correction, so the new content stands. (On a
        corrected chunk the correction wins — see TestCorrectionSurvivesReingest.)"""
        store.upsert_chunks([_chunk(CHUNK_B, seq=1, content="rewritten")])
        chunk = store.get_chunk(CHUNK_B)
        assert chunk is not None
        assert chunk["content"] == "rewritten"


# ── upsert_conflict must not swallow a constraint violation ──


class TestUpsertConflict:
    def test_bad_conflict_type_raises(self, store: SqliteStore) -> None:
        """Before #143 this wrote nothing and reported success — the KB would
        look clean while holding contradictory content."""
        with pytest.raises(Exception, match="CHECK constraint failed"):
            store.upsert_conflict(_conflict(id="conf_00000002", conflict_type="not_a_type"))

    def test_bad_conflict_type_writes_nothing(self, store: SqliteStore) -> None:
        with pytest.raises(Exception, match="CHECK constraint failed"):
            store.upsert_conflict(_conflict(id="conf_00000002", conflict_type="not_a_type"))
        assert store.get_conflict("conf_00000002") is None

    def test_duplicate_id_is_still_a_no_op(self, store: SqliteStore) -> None:
        """Re-detection of a known conflict must stay idempotent — that is
        what OR IGNORE was there for, and the only part worth keeping."""
        store.upsert_conflict(_conflict(similarity=0.1, status="dismissed"))
        existing = store.get_conflict(CONFLICT_ID)
        assert existing is not None
        assert existing["status"] == "open"
        assert existing["similarity"] == pytest.approx(0.9)

    def test_a_duplicate_id_does_not_excuse_an_invalid_row(self, store: SqliteStore) -> None:
        """DO NOTHING absorbs the id collision, not the rest of the row:
        a CHECK violation still raises even when the id is already present."""
        with pytest.raises(Exception, match="CHECK constraint failed"):
            store.upsert_conflict(_conflict(status="not_a_status"))


# ── a correction must survive the re-ingest that overwrites its chunk ──


class TestCorrectionSurvivesReingest:
    """#158 kept the correction *record* alive; without this it would still
    have lost its *effect*, leaving the KB reporting a correction it was not
    serving — worse than losing it outright."""

    def test_reingest_does_not_revert_the_correction(self, store: SqliteStore) -> None:
        store.add_correction(CHUNK_A, "vicente", "wrong port", "VPN auth failure - port 4500")
        # Re-ingest: unchanged source, so the chunker yields the original text
        # under the same content-addressed id.
        store.upsert_chunks([_chunk(CHUNK_A, seq=0)])
        chunk = store.get_chunk(CHUNK_A)
        assert chunk is not None
        assert chunk["content"] == "VPN auth failure - port 4500"

    def test_the_newest_correction_wins(self, store: SqliteStore) -> None:
        """Back-to-back corrections land in the same millisecond, so this
        also pins the rowid tie-break — without it "newest" is undefined."""
        store.add_correction(CHUNK_A, "vicente", "first", "first fix")
        store.add_correction(CHUNK_A, "vicente", "second", "second fix")
        store.upsert_chunks([_chunk(CHUNK_A, seq=0)])
        chunk = store.get_chunk(CHUNK_A)
        assert chunk is not None
        assert chunk["content"] == "second fix"

    def test_an_uncorrected_chunk_takes_the_new_content(self, store: SqliteStore) -> None:
        """Re-application is scoped to chunks that carry a correction."""
        store.upsert_chunks([_chunk(CHUNK_B, seq=1, content="fresh text")])
        chunk = store.get_chunk(CHUNK_B)
        assert chunk is not None
        assert chunk["content"] == "fresh text"

    def test_a_changed_source_is_a_different_chunk(self, store: SqliteStore) -> None:
        """Content addressing does the deciding: different text is a new id,
        so nothing is re-applied to it and the correction stays with the
        chunk it was made against."""
        store.add_correction(CHUNK_A, "vicente", "wrong port", "corrected")
        store.upsert_chunks([_chunk("chk_cccc0003", seq=2, content="rewritten upstream")])
        new_chunk = store.get_chunk("chk_cccc0003")
        old_chunk = store.get_chunk(CHUNK_A)
        assert new_chunk is not None
        assert new_chunk["content"] == "rewritten upstream"
        assert old_chunk is not None
        assert old_chunk["content"] == "corrected"


# ── the removal that used to be a side effect ──


class TestDeleteChunksNotIn:
    def test_removes_only_the_stale_ones(self, store: SqliteStore) -> None:
        removed = store.delete_chunks_not_in(DOC_ID, [CHUNK_A])
        assert removed == 1
        assert store.get_chunk(CHUNK_A) is not None
        assert store.get_chunk(CHUNK_B) is None

    def test_keeping_nothing_clears_the_document(self, store: SqliteStore) -> None:
        assert store.delete_chunks_not_in(DOC_ID, []) == 2
        assert store.get_chunk(CHUNK_A) is None

    def test_a_kept_chunk_keeps_its_correction(self, store: SqliteStore) -> None:
        store.delete_chunks_not_in(DOC_ID, [CHUNK_A, CHUNK_B])
        assert _human_decisions(store) == (1, True)

    def test_reslicing_a_document_needs_the_delete_first(self, store: SqliteStore) -> None:
        """kb_chunks has UNIQUE(document_id, seq) and seq is positional, so a
        re-chunked document collides with its own predecessor. Callers must
        clear the stale set *before* writing the new one — the ordering that
        the removed INSERT OR REPLACE cascade used to provide for free.
        """
        new_set = [
            _chunk("chk_dddd0004", seq=0, content="reslice one"),
            _chunk("chk_eeee0005", seq=1, content="reslice two"),
        ]
        keep = [str(c["id"]) for c in new_set]

        with pytest.raises(Exception, match="UNIQUE constraint failed"):
            store.upsert_chunks(new_set)

        store.delete_chunks_not_in(DOC_ID, keep)
        store.upsert_chunks(new_set)
        assert store.get_chunk("chk_dddd0004") is not None
        assert store.get_chunk(CHUNK_A) is None

    def test_a_stale_chunk_takes_its_conflict_with_it(self, store: SqliteStore) -> None:
        """Correct, not collateral: chunk ids are content-addressed, so a
        chunk absent from the new set holds text that no longer exists."""
        store.delete_chunks_not_in(DOC_ID, [CHUNK_A])
        assert store.get_conflict(CONFLICT_ID) is None
        assert len(store.list_corrections(chunk_id=CHUNK_A)) == 1
