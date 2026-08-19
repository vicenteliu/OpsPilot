"""A second handle must see rows written through the first (#155).

A LanceDB ``Table`` handle pins the dataset version it was opened at. The API
serves each request from whichever uvicorn worker it lands on — the production
compose runs ``--workers 2`` — so an ingest through one worker left the other's
handle looking at a dataset that did not contain the new rows.

The symptom was a document ingest reported as stored, that both stores held on
disk, and that search could not find: the ANN side behaved as though the dataset
were unchanged, while every other result kept its exact order. It reappeared
"on its own" tens of seconds later, which is a request landing on the other
worker.

Two eliminations in the issue were sound and one was not: 20 back-to-back
searches all hitting were taken as evidence against a stale worker, but HTTP
keep-alive pins consecutive requests to one process, so all twenty went to the
same handle.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from opspilot.kb.lance_store import LanceStore, VectorRecord

DIM = 8


def _vec(seed: int) -> list[float]:
    random.seed(seed)
    return [random.random() for _ in range(DIM)]


def _rec(i: int) -> VectorRecord:
    return VectorRecord(
        vector_id=f"vec_{i:08d}",
        embedding=_vec(i),
        document_id="doc_1",
        chunk_id=f"chk_{i:08d}",
        namespace="ns",
        classification="internal",
        language="en",
        tags=[],
        embedding_model="test-model",
    )


@pytest.fixture
def two_handles(tmp_path: Path) -> tuple[LanceStore, LanceStore]:
    """Two handles on one directory — an ingesting worker and a searching one."""
    path = tmp_path / "lancedb"
    writer = LanceStore.open_or_create(path, dim=DIM, embedding_model="test-model")
    writer.upsert_vectors([_rec(i) for i in range(5)])
    reader = LanceStore.open_or_create(path, dim=DIM, embedding_model="test-model")
    return writer, reader


def test_the_other_worker_finds_a_freshly_ingested_chunk(two_handles) -> None:
    writer, reader = two_handles
    writer.upsert_vectors([_rec(99)])
    hits = [h.chunk_id for h in reader.ann_search(_vec(99), top_k=5)]
    assert "chk_00000099" in hits, (
        "the reader's handle is pinned to an older dataset version — ingest "
        "succeeds and search cannot find the document"
    )


def test_the_other_worker_sees_the_new_row_count(two_handles) -> None:
    """count() is what the issue used to conclude 'both stores had the rows'."""
    writer, reader = two_handles
    before = reader.count()
    writer.upsert_vectors([_rec(99)])
    assert reader.count() == before + 1


def test_deletions_are_visible_too(two_handles) -> None:
    writer, reader = two_handles
    writer.delete_by_vector_ids(["vec_00000000"])
    assert "chk_00000000" not in [h.chunk_id for h in reader.ann_search(_vec(0), top_k=5)]


def test_a_refresh_failure_does_not_fail_the_read(two_handles, monkeypatch) -> None:
    """A stale read beats a failed one: the refresh is an improvement, not a gate."""
    _, reader = two_handles

    def _boom() -> None:
        raise RuntimeError("checkout failed")

    monkeypatch.setattr(reader._table, "checkout_latest", _boom)
    assert reader.ann_search(_vec(1), top_k=5)
