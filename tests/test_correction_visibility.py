"""An overridden chunk must not look like an ingested one (#159).

A **Correction** overwrites a Chunk's content in place, and since #158 a
re-ingest of an unchanged document re-asserts that override rather than writing
the source text back over it — correct, and silent.

The system is careful about provenance everywhere else: every **Hit** carries a
**source authority** so a reader can see what a citation rests on, an **Asset
event** outlives its Asset, answers citing a chunk in an open **Conflict** are
flagged. Against that, **the content is the one thing a person changed on
purpose, and it was the one thing not marked** — so an answer disagreeing with
the source file read as a stale index rather than as a deliberate override.

Not covered, and deliberately out of scope per the issue: a correction that stops
applying because the source was fixed and the chunk id changed. Same silence,
opposite direction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite

DOC_ID = "doc_1111aaaa"
PLAIN = "chk_1111aaaa"
OVERRIDDEN = "chk_2222bbbb"


def _doc() -> dict[str, Any]:
    return {
        "id": DOC_ID,
        "source_path": "examples/x/source.md",
        "title": "VPN SOP",
        "classification": "internal",
        "content_hash": "sha256:" + ("a" * 64),
        "ingested_at": "2026-08-18T10:00:00Z",
        "language": "en",
        "tags": [],
        "namespace": "opspilot:public-kb",
        "chunk_strategy": "headings_then_size",
        "chunk_count": 2,
        "embedding_model": "m",
        "embedding_dim": 8,
        "redaction_passed": True,
    }


def _chunk(chunk_id: str, seq: int) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "document_id": DOC_ID,
        "seq": seq,
        "content": f"original text {seq}",
        "content_hash": "sha256:" + ("b" * 64),
        "char_start": 0,
        "char_end": 10,
        "line_start": 1,
        "line_end": 2,
        "heading_path": ["VPN"],
        "anchor": "#vpn",
        "token_count": 4,
        "embedding_model": "m",
        "vector_id": f"vec_{seq:08d}",
        "namespace": "opspilot:public-kb",
        "classification": "internal",
        "language": "en",
        "tags": [],
        "redaction_passed": True,
    }


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    s = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    s.upsert_document(_doc())
    s.upsert_chunks([_chunk(PLAIN, 0), _chunk(OVERRIDDEN, 1)])
    s.add_correction(OVERRIDDEN, corrected_by="user:alice", reason="drift", new_content="corrected")
    return s


def test_only_the_overridden_chunk_is_marked(store: SqliteStore) -> None:
    assert store.get_corrected_chunk_ids([PLAIN, OVERRIDDEN]) == {OVERRIDDEN}


def test_an_empty_query_costs_nothing(store: SqliteStore) -> None:
    assert store.get_corrected_chunk_ids([]) == set()


def test_a_chunk_corrected_twice_is_reported_once(store: SqliteStore) -> None:
    store.add_correction(OVERRIDDEN, corrected_by="user:bob", reason="again", new_content="again")
    assert store.get_corrected_chunk_ids([OVERRIDDEN]) == {OVERRIDDEN}


def test_the_mark_survives_a_reingest(store: SqliteStore) -> None:
    """#158 made the re-assertion correct; this makes it visible."""
    store.upsert_chunks([_chunk(PLAIN, 0), _chunk(OVERRIDDEN, 1)])
    assert store.get_chunk(OVERRIDDEN)["content"] == "corrected"
    assert store.get_corrected_chunk_ids([OVERRIDDEN]) == {OVERRIDDEN}


def test_the_hit_carries_the_flag_beside_the_other_provenance() -> None:
    """It sits with source_authority and has_open_conflicts, not apart from them."""
    from opspilot.kb.retrieval import Hit

    hit = Hit(
        chunk_id=OVERRIDDEN,
        score=1.0,
        rank_vector=1,
        rank_fts=1,
        document_id=DOC_ID,
        namespace="ns",
        content="corrected",
        has_correction=True,
    )
    assert hit.has_correction is True
    assert (
        Hit(
            chunk_id=PLAIN,
            score=1.0,
            rank_vector=1,
            rank_fts=1,
            document_id=DOC_ID,
            namespace="ns",
            content="x",
        ).has_correction
        is False
    )
