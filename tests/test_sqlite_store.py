"""Tests for ``opspilot.kb.sqlite_store``.

Covers KB document/chunk upsert + read, FTS5 BM25 search with namespace /
and classification filters.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from opspilot.kb.sqlite_store import FtsHit, SqliteStore
from opspilot.kb.storage_init import init_sqlite

# ── Helpers ───────────────────────────────────────────────────────────


def _doc(doc_id: str = "doc_88a277cf", **overrides: Any) -> dict[str, Any]:
    base = {
        "id": doc_id,
        "source_path": f"examples/{doc_id}/source.md",
        "title": "VPN 故障排查 SOP（中文）",
        "classification": "internal",
        "content_hash": ("sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"),
        "version": "1.3.0",
        "ingested_at": "2026-05-01T10:00:00Z",
        "language": "zh-CN",
        "tags": ["vpn", "sop"],
        "namespace": "opspilot:public-kb",
        "chunk_strategy": "headings_then_size",
        "chunk_count": 1,
        "embedding_model": "ollama-local/nomic-embed-text@2024-02",
        "embedding_dim": 768,
        "redaction_passed": True,
    }
    base.update(overrides)
    return base


def _chunk(
    chk_id: str = "chk_ea5a0261",
    *,
    doc_id: str = "doc_88a277cf",
    seq: int = 0,
    content: str = "认证失败 VPN 排查",
    namespace: str = "opspilot:public-kb",
    classification: str = "internal",
) -> dict[str, Any]:
    return {
        "id": chk_id,
        "document_id": doc_id,
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
            "namespace": namespace,
            "classification": classification,
            "language": "zh-CN",
        },
    }


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    conn = init_sqlite(tmp_path / "kb.db")
    return SqliteStore(conn)


# ── KB documents ──────────────────────────────────────────────────────


def test_upsert_and_get_document(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    row = store.get_document("doc_88a277cf")
    assert row is not None
    assert row["title"] == "VPN 故障排查 SOP（中文）"
    assert row["tags_json"] == ["vpn", "sop"]
    assert row["embedding_dim"] == 768
    assert row["redaction_passed"] == 1


def test_upsert_document_replaces_by_id(store: SqliteStore) -> None:
    store.upsert_document(_doc(title="v1"))
    store.upsert_document(_doc(title="v2"))
    row = store.get_document("doc_88a277cf")
    assert row is not None
    assert row["title"] == "v2"


def test_get_document_missing_returns_none(store: SqliteStore) -> None:
    assert store.get_document("doc_00000000") is None


def test_upsert_document_rejects_unredacted(store: SqliteStore) -> None:
    with pytest.raises(ValueError, match="redaction_passed"):
        store.upsert_document(_doc(redaction_passed=False))


def test_doc_id_glob_constraint(store: SqliteStore) -> None:
    # SQLite CHECK should reject ids that don't match doc_<sha8>.
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_document(_doc(doc_id="bad-id"))


def test_doc_classification_constraint(store: SqliteStore) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_document(_doc(classification="top-secret"))


# ── KB chunks ─────────────────────────────────────────────────────────


def test_upsert_chunks_batch(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    n = store.upsert_chunks(
        [
            _chunk("chk_aaaaaaaa", seq=0),
            _chunk("chk_bbbbbbbb", seq=1, content="网络层"),
            _chunk("chk_cccccccc", seq=2, content="MTU 调整"),
        ]
    )
    assert n == 3

    row = store.get_chunk("chk_bbbbbbbb")
    assert row is not None
    assert row["seq"] == 1
    assert row["content"] == "网络层"
    assert row["heading_path_json"] == ["VPN SOP"]


def test_upsert_chunks_empty_list_is_zero(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    assert store.upsert_chunks([]) == 0


def test_chunk_id_glob_constraint(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_chunks([_chunk("chunk_bad")])


def test_chunk_doc_fk_required(store: SqliteStore) -> None:
    # Document doesn't exist → FK violation.
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_chunks([_chunk(doc_id="doc_99999999")])


def test_chunk_content_xor_artifact(store: SqliteStore) -> None:
    """Schema enforces (content XOR content_artifact_id)."""
    store.upsert_document(_doc())
    bad = _chunk()
    bad["content"] = None
    bad["content_artifact_id"] = None
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_chunks([bad])


def test_get_chunks_by_vector_ids(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    store.upsert_chunks(
        [
            _chunk("chk_aaaaaaaa", seq=0),
            _chunk("chk_bbbbbbbb", seq=1, content="ESP NAT-T"),
        ]
    )
    out = store.get_chunks_by_vector_ids(
        ["vec_chk_aaaaaaaa", "vec_chk_bbbbbbbb", "vec_chk_missing"]
    )
    assert set(out.keys()) == {"vec_chk_aaaaaaaa", "vec_chk_bbbbbbbb"}
    assert out["vec_chk_bbbbbbbb"]["content"] == "ESP NAT-T"


def test_get_chunks_by_vector_ids_empty(store: SqliteStore) -> None:
    assert store.get_chunks_by_vector_ids([]) == {}


# ── FTS5 search ───────────────────────────────────────────────────────


def test_fts_search_finds_matching_chunk(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    store.upsert_chunks(
        [
            _chunk(
                "chk_aaaaaaaa",
                seq=0,
                content="authentication failed peer auth failed",
            ),
            _chunk(
                "chk_bbbbbbbb",
                seq=1,
                content="MTU adjustments for tunnel",
            ),
        ]
    )
    hits = store.fts_search("authentication", top_k=5)
    assert len(hits) == 1
    assert hits[0].chunk_id == "chk_aaaaaaaa"
    assert hits[0].score > 0  # flipped sign → higher = better
    assert isinstance(hits[0], FtsHit)


def test_fts_search_ranking_higher_is_better(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    store.upsert_chunks(
        [
            _chunk(
                "chk_aaaaaaaa",
                seq=0,
                content="auth auth auth network MTU",
            ),
            _chunk(
                "chk_bbbbbbbb",
                seq=1,
                content="auth network only mentioned once",
            ),
        ]
    )
    hits = store.fts_search("auth", top_k=5)
    assert [h.chunk_id for h in hits] == ["chk_aaaaaaaa", "chk_bbbbbbbb"]
    assert hits[0].score >= hits[1].score


def test_fts_search_namespace_filter(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    store.upsert_chunks(
        [
            _chunk(
                "chk_aaaaaaaa",
                seq=0,
                content="auth",
                namespace="opspilot:public-kb",
            ),
            _chunk(
                "chk_bbbbbbbb",
                seq=1,
                content="auth",
                namespace="opspilot:public-kb",
            ),
        ]
    )
    # Different namespace doc.
    store.upsert_document(_doc(doc_id="doc_aabbccdd"))
    store.upsert_chunks(
        [
            _chunk(
                "chk_dddddddd",
                doc_id="doc_aabbccdd",
                seq=0,
                content="auth in private-kb",
                namespace="opspilot:private-kb",
            ),
        ]
    )

    hits = store.fts_search("auth", top_k=5, namespace="opspilot:public-kb")
    chunk_ids = {h.chunk_id for h in hits}
    assert "chk_dddddddd" not in chunk_ids
    assert chunk_ids == {"chk_aaaaaaaa", "chk_bbbbbbbb"}


def test_fts_search_classification_filter(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    store.upsert_chunks(
        [
            _chunk("chk_aaaaaaaa", seq=0, content="auth", classification="public"),
            _chunk("chk_bbbbbbbb", seq=1, content="auth", classification="internal"),
        ]
    )
    hits = store.fts_search("auth", top_k=5, classification="public")
    assert {h.chunk_id for h in hits} == {"chk_aaaaaaaa"}


def test_fts_search_empty_query_returns_empty(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    store.upsert_chunks([_chunk()])
    assert store.fts_search("") == []
    assert store.fts_search("   ") == []


def test_fts_search_top_k_bounds(store: SqliteStore) -> None:
    store.upsert_document(_doc())
    store.upsert_chunks([_chunk(f"chk_{i:08x}", seq=i, content="auth term") for i in range(5)])
    hits = store.fts_search("auth", top_k=2)
    assert len(hits) == 2
