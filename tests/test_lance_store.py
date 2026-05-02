"""Tests for ``opspilot.memory.lance_store``.

Uses deterministic mock vectors (no embedding model required). Each test
uses a fresh tmp_path so datasets don't leak between cases.

Vector layout (4-dim for clarity):
    v_a = [1, 0, 0, 0]   # "auth" cluster
    v_b = [0, 1, 0, 0]   # "network" cluster
    v_c = [0, 0, 1, 0]   # unrelated
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# LanceDB writes to a user-config dir; redirect to tmp before import so the
# sandbox warning disappears in CI.
os.environ.setdefault("LANCEDB_CONFIG_DIR", "/tmp/lancedb-config")

from opspilot.memory.lance_store import (  # noqa: E402
    AnnHit,
    LanceStore,
    VectorRecord,
)

DIM = 4
EMBED_MODEL = "ollama-local/nomic-embed-text@2024-02"


def _rec(
    chunk_id: str,
    embedding: list[float],
    *,
    namespace: str = "opspilot:public-kb",
    classification: str = "internal",
    language: str = "zh-CN",
    tags: list[str] | None = None,
    document_id: str = "doc_88a277cf",
) -> VectorRecord:
    return VectorRecord(
        vector_id=f"vec_{chunk_id}",
        embedding=embedding,
        document_id=document_id,
        chunk_id=chunk_id,
        namespace=namespace,
        classification=classification,
        language=language,
        tags=tags or [],
        embedding_model=EMBED_MODEL,
    )


@pytest.fixture
def store(tmp_path: Path) -> LanceStore:
    return LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)


# ── Open / create ─────────────────────────────────────────────────────


def test_open_or_create_makes_directory(tmp_path: Path) -> None:
    p = tmp_path / "lancedb"
    LanceStore.open_or_create(p, dim=DIM, embedding_model=EMBED_MODEL)
    assert p.is_dir()


def test_open_existing_table_preserves_data(tmp_path: Path) -> None:
    p = tmp_path / "lancedb"
    s1 = LanceStore.open_or_create(p, dim=DIM, embedding_model=EMBED_MODEL)
    s1.upsert_vectors([_rec("chk_aaaaaaaa", [1, 0, 0, 0])])
    assert s1.count() == 1

    s2 = LanceStore.open_or_create(p, dim=DIM, embedding_model=EMBED_MODEL)
    assert s2.count() == 1


def test_dim_mismatch_on_reopen_raises(tmp_path: Path) -> None:
    p = tmp_path / "lancedb"
    LanceStore.open_or_create(p, dim=DIM, embedding_model=EMBED_MODEL)
    with pytest.raises(ValueError, match="dim"):
        LanceStore.open_or_create(p, dim=8, embedding_model=EMBED_MODEL)


# ── Upsert ────────────────────────────────────────────────────────────


def test_upsert_inserts_then_updates(store: LanceStore) -> None:
    n = store.upsert_vectors([_rec("chk_aaaaaaaa", [1, 0, 0, 0])])
    assert n == 1
    assert store.count() == 1

    # Re-upsert with same vector_id (different embedding) should update,
    # not duplicate.
    store.upsert_vectors([_rec("chk_aaaaaaaa", [0.5, 0.5, 0, 0])])
    assert store.count() == 1


def test_upsert_empty_returns_zero(store: LanceStore) -> None:
    assert store.upsert_vectors([]) == 0
    assert store.count() == 0


def test_upsert_rejects_wrong_dim(store: LanceStore) -> None:
    with pytest.raises(ValueError, match="length"):
        store.upsert_vectors([_rec("chk_aaaaaaaa", [1, 0, 0])])  # 3-dim


def test_upsert_rejects_mismatched_embedding_model(store: LanceStore) -> None:
    bad = VectorRecord(
        vector_id="vec_chk_bad",
        embedding=[1, 0, 0, 0],
        document_id="doc_88a277cf",
        chunk_id="chk_bad",
        namespace="opspilot:public-kb",
        classification="internal",
        language="zh-CN",
        tags=[],
        embedding_model="other-provider/other-model@2024-09",
    )
    with pytest.raises(ValueError, match="embedding_model"):
        store.upsert_vectors([bad])


# ── ANN search ────────────────────────────────────────────────────────


def test_ann_search_top1_matches_nearest(store: LanceStore) -> None:
    store.upsert_vectors(
        [
            _rec("chk_aaaaaaaa", [1, 0, 0, 0]),
            _rec("chk_bbbbbbbb", [0, 1, 0, 0]),
            _rec("chk_cccccccc", [0, 0, 1, 0]),
        ]
    )
    hits = store.ann_search([0.99, 0.01, 0, 0], top_k=1)
    assert len(hits) == 1
    assert isinstance(hits[0], AnnHit)
    assert hits[0].vector_id == "vec_chk_aaaaaaaa"
    assert hits[0].chunk_id == "chk_aaaaaaaa"
    # cosine similarity should be very close to 1.0.
    assert hits[0].score > 0.99


def test_ann_search_returns_top_k_in_order(store: LanceStore) -> None:
    store.upsert_vectors(
        [
            _rec("chk_aaaaaaaa", [1, 0, 0, 0]),
            _rec("chk_bbbbbbbb", [0.7, 0.7, 0, 0]),
            _rec("chk_cccccccc", [0, 1, 0, 0]),
            _rec("chk_dddddddd", [0, 0, 1, 0]),
        ]
    )
    hits = store.ann_search([1, 0, 0, 0], top_k=3)
    chunk_ids = [h.chunk_id for h in hits]
    # nearest → second-nearest → third-nearest by cosine.
    assert chunk_ids == ["chk_aaaaaaaa", "chk_bbbbbbbb", "chk_cccccccc"]
    # Scores monotonically decreasing.
    assert hits[0].score > hits[1].score > hits[2].score


def test_ann_search_namespace_filter(store: LanceStore) -> None:
    store.upsert_vectors(
        [
            _rec(
                "chk_aaaaaaaa",
                [1, 0, 0, 0],
                namespace="opspilot:public-kb",
            ),
            _rec(
                "chk_bbbbbbbb",
                [1, 0, 0, 0],  # same vector, different ns
                namespace="opspilot:private-kb",
                document_id="doc_88a277ff",
            ),
        ]
    )
    hits = store.ann_search([1, 0, 0, 0], top_k=5, namespace="opspilot:public-kb")
    assert {h.chunk_id for h in hits} == {"chk_aaaaaaaa"}


def test_ann_search_classification_filter(store: LanceStore) -> None:
    store.upsert_vectors(
        [
            _rec("chk_aaaaaaaa", [1, 0, 0, 0], classification="public"),
            _rec("chk_bbbbbbbb", [1, 0, 0, 0], classification="internal"),
        ]
    )
    hits = store.ann_search([1, 0, 0, 0], top_k=5, classification="public")
    assert {h.chunk_id for h in hits} == {"chk_aaaaaaaa"}


def test_ann_search_rejects_wrong_query_dim(store: LanceStore) -> None:
    with pytest.raises(ValueError, match="length"):
        store.ann_search([1, 0, 0], top_k=1)


def test_ann_search_empty_table_returns_empty(store: LanceStore) -> None:
    assert store.ann_search([1, 0, 0, 0], top_k=5) == []


# ── Delete ────────────────────────────────────────────────────────────


def test_delete_by_vector_ids(store: LanceStore) -> None:
    store.upsert_vectors(
        [
            _rec("chk_aaaaaaaa", [1, 0, 0, 0]),
            _rec("chk_bbbbbbbb", [0, 1, 0, 0]),
        ]
    )
    store.delete_by_vector_ids(["vec_chk_aaaaaaaa"])
    assert store.count() == 1
    hits = store.ann_search([1, 0, 0, 0], top_k=5)
    assert all(h.vector_id != "vec_chk_aaaaaaaa" for h in hits)


def test_delete_empty_is_noop(store: LanceStore) -> None:
    store.upsert_vectors([_rec("chk_aaaaaaaa", [1, 0, 0, 0])])
    store.delete_by_vector_ids([])
    assert store.count() == 1
