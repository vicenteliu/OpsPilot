"""Tests for memory.conflict — detection and resolution logic."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from opspilot.memory.conflict import (
    _classify_conflict,
    _has_contradiction,
    detect_and_store_conflicts,
    resolve_conflict,
)
from opspilot.memory.lance_store import AnnHit
from opspilot.memory.sqlite_store import SqliteStore
from opspilot.memory.storage_init import init_sqlite

DIM = 3
EMBED_MODEL = "test/mock"


# ── Shared fixture ────────────────────────────────────────────────────


@pytest.fixture
def sqlite(tmp_path: Path) -> SqliteStore:
    return SqliteStore(init_sqlite(tmp_path / "kb.db"))


def _upsert_doc(
    sqlite: SqliteStore, doc_id: str, title: str = "doc", valid_from: str | None = None
) -> None:
    sqlite.upsert_document(
        {
            "id": doc_id,
            "source_path": f"/{doc_id}.md",
            "title": title,
            "classification": "internal",
            "content_hash": "sha256:" + ("a" * 64),
            "ingested_at": "2026-01-01T00:00:00Z",
            "language": "en",
            "tags": [],
            "namespace": "ns",
            "chunk_strategy": "headings_then_size",
            "chunk_count": 1,
            "embedding_model": EMBED_MODEL,
            "embedding_dim": DIM,
            "redaction_passed": True,
            "valid_from": valid_from,
        }
    )


def _upsert_chunk(
    sqlite: SqliteStore, chunk_id: str, doc_id: str, content: str = "hello"
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": chunk_id,
        "document_id": doc_id,
        "seq": 0,
        "content": content,
        "content_hash": "sha256:" + ("b" * 64),
        "char_start": 0,
        "char_end": len(content),
        "line_start": 1,
        "line_end": 1,
        "embedding_model": EMBED_MODEL,
        "vector_id": f"vec_{chunk_id}",
        "metadata": {"namespace": "ns", "classification": "internal", "language": "en", "tags": []},
    }
    sqlite.upsert_chunks([row])
    return row


# ── _has_contradiction ────────────────────────────────────────────────


def test_has_contradiction_disabled_vs_enabled() -> None:
    assert _has_contradiction("feature is disabled", "feature is enabled")


def test_has_contradiction_supported_vs_not_supported() -> None:
    assert _has_contradiction("this is not supported", "this is supported")


def test_has_contradiction_reversed_order() -> None:
    assert _has_contradiction("this is supported", "this is not supported")


def test_has_contradiction_cjk_enabled_disabled() -> None:
    assert _has_contradiction("功能已启用", "功能已禁用")


def test_has_contradiction_no_match() -> None:
    assert not _has_contradiction("restart the service", "restart the service")


def test_has_contradiction_unrelated_text() -> None:
    assert not _has_contradiction("set the timeout to 30s", "configure the firewall rule")


# ── _classify_conflict ────────────────────────────────────────────────


def test_classify_temporal_supersede_30_day_gap() -> None:
    result = _classify_conflict(
        "2026-01-01T00:00:00Z",
        "2026-03-01T00:00:00Z",  # 59 days later
        "same content",
        "same content",
    )
    assert result == "temporal_supersede"


def test_classify_temporal_supersede_exactly_30_days() -> None:
    result = _classify_conflict(
        "2026-01-01T00:00:00Z",
        "2026-01-31T00:00:00Z",
        "content",
        "content",
    )
    assert result == "temporal_supersede"


def test_classify_direct_contradiction_when_no_temporal_gap() -> None:
    result = _classify_conflict(
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",  # only 1 day
        "the feature is disabled",
        "the feature is enabled",
    )
    assert result == "direct_contradiction"


def test_classify_scope_overlap_default() -> None:
    result = _classify_conflict(None, None, "some content", "similar content")
    assert result == "scope_overlap"


def test_classify_scope_overlap_when_valid_from_missing() -> None:
    result = _classify_conflict(None, "2026-01-01T00:00:00Z", "content a", "content b")
    assert result == "scope_overlap"


# ── detect_and_store_conflicts ────────────────────────────────────────


@pytest.fixture
def two_doc_kb(sqlite: SqliteStore) -> tuple[SqliteStore, str, list[dict], str]:
    """Two documents with one chunk each; returns (sqlite, new_doc_id, new_chunks, existing_chunk_id)."""
    _upsert_doc(sqlite, "doc_aaaaaaaa", title="Old doc", valid_from="2026-01-01T00:00:00Z")
    existing = _upsert_chunk(
        sqlite,
        "chk_aaaaaaaa",
        "doc_aaaaaaaa",
        content="VPN authentication fails — please check credentials",
    )

    _upsert_doc(sqlite, "doc_bbbbbbbb", title="New doc", valid_from="2026-03-01T00:00:00Z")
    new_chunk = _upsert_chunk(
        sqlite,
        "chk_bbbbbbbb",
        "doc_bbbbbbbb",
        content="VPN authentication failure — verify username and password",
    )

    return sqlite, "doc_bbbbbbbb", [new_chunk], existing["id"]


def test_detect_creates_conflict_record(two_doc_kb: Any) -> None:
    sqlite, new_doc_id, new_chunks, existing_chunk_id = two_doc_kb

    # Mock lance: ann_search returns the existing chunk as a near-duplicate
    lance = MagicMock()
    lance.ann_search.return_value = [
        AnnHit(
            vector_id="vec_chk_aaaaaaaa",
            score=0.90,
            chunk_id=existing_chunk_id,
            document_id="doc_aaaaaaaa",
            namespace="ns",
        )
    ]

    def embed_fn(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    created = detect_and_store_conflicts(
        new_doc_id=new_doc_id,
        new_chunks=new_chunks,
        lance=lance,
        sqlite=sqlite,
        embed_fn=embed_fn,
        similarity_threshold=0.85,
    )

    assert created == 1
    conflicts = sqlite.list_conflicts(status="open")
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["status"] == "open"
    assert c["similarity"] == pytest.approx(0.90)
    # conflict_type should be temporal_supersede (both docs have valid_from, 59-day gap)
    assert c["conflict_type"] == "temporal_supersede"


def test_detect_skips_same_document_chunks(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    chunk = _upsert_chunk(
        sqlite,
        "chk_aaaaaaaa",
        "doc_aaaaaaaa",
        content="VPN authentication fails — please check firewall rules",
    )

    lance = MagicMock()
    # ANN returns the chunk from the *same* document — must be skipped
    lance.ann_search.return_value = [
        AnnHit(
            vector_id="vec_chk_aaaaaaaa",
            score=0.99,
            chunk_id="chk_aaaaaaaa",
            document_id="doc_aaaaaaaa",
            namespace="ns",
        )
    ]

    created = detect_and_store_conflicts(
        new_doc_id="doc_aaaaaaaa",
        new_chunks=[chunk],
        lance=lance,
        sqlite=sqlite,
        embed_fn=lambda t: [1.0, 0.0, 0.0],
    )

    assert created == 0


def test_detect_below_threshold_not_stored(two_doc_kb: Any) -> None:
    sqlite, new_doc_id, new_chunks, existing_chunk_id = two_doc_kb

    lance = MagicMock()
    lance.ann_search.return_value = [
        AnnHit(
            vector_id="vec_chk_aaaaaaaa",
            score=0.70,  # below threshold
            chunk_id=existing_chunk_id,
            document_id="doc_aaaaaaaa",
            namespace="ns",
        )
    ]

    created = detect_and_store_conflicts(
        new_doc_id=new_doc_id,
        new_chunks=new_chunks,
        lance=lance,
        sqlite=sqlite,
        embed_fn=lambda t: [1.0, 0.0, 0.0],
        similarity_threshold=0.85,
    )

    assert created == 0


def test_detect_idempotent_on_same_pair(two_doc_kb: Any) -> None:
    sqlite, new_doc_id, new_chunks, existing_chunk_id = two_doc_kb

    ann_hit = AnnHit(
        vector_id="vec_chk_aaaaaaaa",
        score=0.90,
        chunk_id=existing_chunk_id,
        document_id="doc_aaaaaaaa",
        namespace="ns",
    )
    lance = MagicMock()
    lance.ann_search.return_value = [ann_hit]

    kwargs: dict[str, Any] = {
        "new_doc_id": new_doc_id,
        "new_chunks": new_chunks,
        "lance": lance,
        "sqlite": sqlite,
        "embed_fn": lambda t: [1.0, 0.0, 0.0],
        "similarity_threshold": 0.85,
    }
    detect_and_store_conflicts(**kwargs)
    created2 = detect_and_store_conflicts(**kwargs)  # second call must be a no-op

    assert created2 == 0
    assert len(sqlite.list_conflicts()) == 1


# ── resolve_conflict ──────────────────────────────────────────────────


@pytest.fixture
def open_conflict(sqlite: SqliteStore) -> tuple[SqliteStore, str]:
    """One open conflict; returns (sqlite, conflict_id)."""
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_doc(sqlite, "doc_bbbbbbbb")
    chunk_a = _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa")
    chunk_b = _upsert_chunk(sqlite, "chk_bbbbbbbb", "doc_bbbbbbbb")

    sqlite.upsert_conflict(
        {
            "id": "conf_abcd1234",
            "chunk_a_id": chunk_a["id"],
            "chunk_b_id": chunk_b["id"],
            "doc_a_id": "doc_aaaaaaaa",
            "doc_b_id": "doc_bbbbbbbb",
            "conflict_type": "scope_overlap",
            "similarity": 0.88,
            "status": "open",
            "detected_at": "2026-05-06T00:00:00Z",
        }
    )
    return sqlite, "conf_abcd1234"


def test_resolve_a_wins_marks_chunk_b_superseded(open_conflict: Any) -> None:
    sqlite, conf_id = open_conflict
    resolve_conflict(conf_id, resolution="a_wins", resolved_by="tester", sqlite=sqlite)

    conf = sqlite.get_conflict(conf_id)
    assert conf is not None
    assert conf["status"] == "a_wins"
    assert conf["resolved_by"] == "tester"

    chunk_b = sqlite.get_chunk("chk_bbbbbbbb")
    assert chunk_b is not None
    assert chunk_b["superseded_by"] == "chk_aaaaaaaa"


def test_resolve_b_wins_marks_chunk_a_superseded(open_conflict: Any) -> None:
    sqlite, conf_id = open_conflict
    resolve_conflict(conf_id, resolution="b_wins", resolved_by="tester", sqlite=sqlite)

    chunk_a = sqlite.get_chunk("chk_aaaaaaaa")
    assert chunk_a is not None
    assert chunk_a["superseded_by"] == "chk_bbbbbbbb"


def test_resolve_merged_no_superseded(open_conflict: Any) -> None:
    sqlite, conf_id = open_conflict
    resolve_conflict(conf_id, resolution="merged", resolved_by="tester", sqlite=sqlite)

    # Neither chunk should be marked superseded for 'merged'
    assert sqlite.get_chunk("chk_aaaaaaaa")["superseded_by"] is None  # type: ignore[index]
    assert sqlite.get_chunk("chk_bbbbbbbb")["superseded_by"] is None  # type: ignore[index]


def test_resolve_dismissed(open_conflict: Any) -> None:
    sqlite, conf_id = open_conflict
    resolve_conflict(
        conf_id, resolution="dismissed", resolved_by="bot", note="false positive", sqlite=sqlite
    )

    conf = sqlite.get_conflict(conf_id)
    assert conf is not None
    assert conf["status"] == "dismissed"
    assert conf["resolution_note"] == "false positive"


def test_resolve_invalid_resolution_raises(open_conflict: Any) -> None:
    sqlite, conf_id = open_conflict
    with pytest.raises(ValueError, match="resolution must be one of"):
        resolve_conflict(conf_id, resolution="bad_value", resolved_by="tester", sqlite=sqlite)


def test_resolve_missing_conflict_raises(sqlite: SqliteStore) -> None:
    with pytest.raises(KeyError, match="conf_notfound"):
        resolve_conflict(
            "conf_notfound", resolution="dismissed", resolved_by="tester", sqlite=sqlite
        )


# ── exclude_superseded in retrieval ──────────────────────────────────


def test_get_superseded_chunk_ids_returns_correct_set(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_doc(sqlite, "doc_bbbbbbbb")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa")
    _upsert_chunk(sqlite, "chk_bbbbbbbb", "doc_bbbbbbbb")

    sqlite.mark_chunk_superseded("chk_aaaaaaaa", superseded_by="chk_bbbbbbbb")

    superseded = sqlite.get_superseded_chunk_ids(["chk_aaaaaaaa", "chk_bbbbbbbb"])
    assert superseded == {"chk_aaaaaaaa"}


def test_get_superseded_chunk_ids_empty_input(sqlite: SqliteStore) -> None:
    assert sqlite.get_superseded_chunk_ids([]) == set()


def test_fts_search_excludes_superseded_by_default(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_doc(sqlite, "doc_bbbbbbbb")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa", content="VPN authentication failure")
    _upsert_chunk(
        sqlite, "chk_bbbbbbbb", "doc_bbbbbbbb", content="VPN authentication failure fixed"
    )

    sqlite.mark_chunk_superseded("chk_aaaaaaaa", superseded_by="chk_bbbbbbbb")

    hits = sqlite.fts_search('"VPN"', top_k=10)
    ids = {h.chunk_id for h in hits}
    assert "chk_aaaaaaaa" not in ids
    assert "chk_bbbbbbbb" in ids


def test_fts_search_include_superseded_when_flag_off(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa", content="VPN authentication failure")
    sqlite.mark_chunk_superseded("chk_aaaaaaaa", superseded_by="chk_cccccccc")

    hits = sqlite.fts_search('"VPN"', top_k=10, exclude_superseded=False)
    assert any(h.chunk_id == "chk_aaaaaaaa" for h in hits)


# ── get_docs_with_open_conflicts / has_open_conflicts ─────────────────


def test_get_docs_with_open_conflicts_returns_affected_docs(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_doc(sqlite, "doc_bbbbbbbb")
    _upsert_doc(sqlite, "doc_cccccccc")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa")
    _upsert_chunk(sqlite, "chk_bbbbbbbb", "doc_bbbbbbbb")

    sqlite.upsert_conflict(
        {
            "id": "conf_abcd1234",
            "chunk_a_id": "chk_aaaaaaaa",
            "chunk_b_id": "chk_bbbbbbbb",
            "doc_a_id": "doc_aaaaaaaa",
            "doc_b_id": "doc_bbbbbbbb",
            "conflict_type": "scope_overlap",
            "similarity": 0.88,
            "status": "open",
            "detected_at": "2026-05-06T00:00:00Z",
        }
    )

    result = sqlite.get_docs_with_open_conflicts(["doc_aaaaaaaa", "doc_bbbbbbbb", "doc_cccccccc"])
    assert result == {"doc_aaaaaaaa", "doc_bbbbbbbb"}


def test_get_docs_with_open_conflicts_excludes_resolved(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_doc(sqlite, "doc_bbbbbbbb")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa")
    _upsert_chunk(sqlite, "chk_bbbbbbbb", "doc_bbbbbbbb")

    sqlite.upsert_conflict(
        {
            "id": "conf_abcd1234",
            "chunk_a_id": "chk_aaaaaaaa",
            "chunk_b_id": "chk_bbbbbbbb",
            "doc_a_id": "doc_aaaaaaaa",
            "doc_b_id": "doc_bbbbbbbb",
            "conflict_type": "scope_overlap",
            "similarity": 0.88,
            "status": "a_wins",  # already resolved
            "detected_at": "2026-05-06T00:00:00Z",
        }
    )

    result = sqlite.get_docs_with_open_conflicts(["doc_aaaaaaaa", "doc_bbbbbbbb"])
    assert result == set()


def test_get_docs_with_open_conflicts_empty_input(sqlite: SqliteStore) -> None:
    assert sqlite.get_docs_with_open_conflicts([]) == set()


def test_kb_search_sets_has_open_conflicts(tmp_path: Path) -> None:
    """kb_search marks hits whose source doc has an open conflict."""
    import math

    from opspilot.memory.lance_store import LanceStore, VectorRecord
    from opspilot.memory.retrieval import kb_search

    DIM = 3
    MODEL = "test/mock"

    sqlite_store = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=MODEL)

    # Three docs: doc_a and doc_b are in conflict; doc_c is clean
    for doc_id, title in (
        ("doc_aaaaaaaa", "Conflict doc A"),
        ("doc_bbbbbbbb", "Conflict doc B"),
        ("doc_cccccccc", "Clean doc"),
    ):
        sqlite_store.upsert_document(
            {
                "id": doc_id,
                "source_path": f"/{doc_id}.md",
                "title": title,
                "classification": "internal",
                "content_hash": "sha256:" + ("a" * 64),
                "ingested_at": "2026-01-01T00:00:00Z",
                "language": "en",
                "tags": [],
                "namespace": "ns",
                "chunk_strategy": "headings_then_size",
                "chunk_count": 1,
                "embedding_model": MODEL,
                "embedding_dim": DIM,
                "redaction_passed": True,
            }
        )

    for chunk_id, doc_id, content in (
        ("chk_aaaaaaaa", "doc_aaaaaaaa", "VPN authentication fails"),
        ("chk_bbbbbbbb", "doc_bbbbbbbb", "VPN authentication failure"),
        ("chk_cccccccc", "doc_cccccccc", "VPN connection success"),
    ):
        row: dict[str, Any] = {
            "id": chunk_id,
            "document_id": doc_id,
            "seq": 0,
            "content": content,
            "content_hash": "sha256:" + (chunk_id[-8:] * 8),
            "char_start": 0,
            "char_end": len(content),
            "line_start": 1,
            "line_end": 1,
            "embedding_model": MODEL,
            "vector_id": f"vec_{chunk_id}",
            "metadata": {
                "namespace": "ns",
                "classification": "internal",
                "language": "en",
                "tags": [],
            },
        }
        sqlite_store.upsert_chunks([row])
        vec = [1.0, 0.0, 0.0]
        norm = math.sqrt(sum(x * x for x in vec))
        lance.upsert_vectors(
            [
                VectorRecord(
                    vector_id=f"vec_{chunk_id}",
                    embedding=[x / norm for x in vec],
                    document_id=doc_id,
                    chunk_id=chunk_id,
                    namespace="ns",
                    classification="internal",
                    language="en",
                    tags=[],
                    embedding_model=MODEL,
                )
            ]
        )

    # Open conflict between doc_a and doc_b; doc_c is untouched
    sqlite_store.upsert_conflict(
        {
            "id": "conf_abcd1234",
            "chunk_a_id": "chk_aaaaaaaa",
            "chunk_b_id": "chk_bbbbbbbb",
            "doc_a_id": "doc_aaaaaaaa",
            "doc_b_id": "doc_bbbbbbbb",
            "conflict_type": "scope_overlap",
            "similarity": 0.88,
            "status": "open",
            "detected_at": "2026-05-06T00:00:00Z",
        }
    )

    hits = kb_search(
        "VPN",
        sqlite=sqlite_store,
        lance=lance,
        embed_fn=lambda _: [1.0, 0.0, 0.0],
        top_k=5,
    )

    hits_by_doc = {h.document_id: h for h in hits}
    # Both sides of the conflict are flagged
    assert hits_by_doc["doc_aaaaaaaa"].has_open_conflicts is True
    assert hits_by_doc["doc_bbbbbbbb"].has_open_conflicts is True
    # Unrelated doc is clean
    assert hits_by_doc["doc_cccccccc"].has_open_conflicts is False


# ── add_correction / list_corrections ─────────────────────────────────


def test_add_correction_updates_chunk_content(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa", content="old content here")
    corr_id = sqlite.add_correction(
        "chk_aaaaaaaa",
        corrected_by="tester",
        reason="typo fix",
        new_content="new content here",
    )
    assert corr_id.startswith("corr_")
    row = sqlite.get_chunk("chk_aaaaaaaa")
    assert row is not None
    assert row["content"] == "new content here"


def test_add_correction_records_old_content(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa", content="original text")
    corr_id = sqlite.add_correction(
        "chk_aaaaaaaa",
        corrected_by="tester",
        reason="wrong info",
        new_content="corrected text",
    )
    corrections = sqlite.list_corrections(chunk_id="chk_aaaaaaaa")
    assert len(corrections) == 1
    assert corrections[0]["id"] == corr_id
    assert corrections[0]["old_content"] == "original text"
    assert corrections[0]["new_content"] == "corrected text"
    assert corrections[0]["reason"] == "wrong info"
    assert corrections[0]["corrected_by"] == "tester"


def test_add_correction_raises_for_unknown_chunk(sqlite: SqliteStore) -> None:
    with pytest.raises(KeyError, match="chk_aaaaaaaa"):
        sqlite.add_correction(
            "chk_aaaaaaaa",
            corrected_by="tester",
            reason="x",
            new_content="y",
        )


def test_list_corrections_returns_both_for_chunk(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa", content="v0")
    sqlite.add_correction("chk_aaaaaaaa", corrected_by="a", reason="r1", new_content="v1")
    sqlite.add_correction("chk_aaaaaaaa", corrected_by="b", reason="r2", new_content="v2")
    corrections = sqlite.list_corrections(chunk_id="chk_aaaaaaaa")
    assert len(corrections) == 2
    new_contents = {c["new_content"] for c in corrections}
    assert new_contents == {"v1", "v2"}


def test_list_corrections_without_filter(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_doc(sqlite, "doc_bbbbbbbb")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa", content="x")
    _upsert_chunk(sqlite, "chk_bbbbbbbb", "doc_bbbbbbbb", content="y")
    sqlite.add_correction("chk_aaaaaaaa", corrected_by="u", reason="r", new_content="x2")
    sqlite.add_correction("chk_bbbbbbbb", corrected_by="u", reason="r", new_content="y2")
    all_corrections = sqlite.list_corrections()
    assert len(all_corrections) == 2


def test_list_corrections_respects_limit(sqlite: SqliteStore) -> None:
    _upsert_doc(sqlite, "doc_aaaaaaaa")
    _upsert_chunk(sqlite, "chk_aaaaaaaa", "doc_aaaaaaaa", content="start")
    for i in range(5):
        sqlite.add_correction("chk_aaaaaaaa", corrected_by="u", reason="r", new_content=f"v{i}")
    assert len(sqlite.list_corrections(limit=3)) == 3
