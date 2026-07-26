"""Regression: API ingest must populate the vector table, not just FTS.

The route once stamped records with a fabricated embedding_model ref while
the LanceStore was opened with the bare model name; upsert_vectors rejected
every record, the FTS write still committed, and the KB ended up with
keyword chunks and zero vectors. This asserts vectors actually land.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.kb import router as kb_router
from opspilot.memory.lance_store import LanceStore
from opspilot.memory.sqlite_store import SqliteStore
from opspilot.memory.storage_init import init_sqlite
from opspilot.redaction import Redactor

_DIM = 8


def _embed(text: str) -> list[float]:
    # Deterministic non-zero vector; content-insensitive is fine for the count.
    return [float(len(text) % 7) + 1.0] + [0.1] * (_DIM - 1)


def _client(tmp_path: Path, table_model: str) -> tuple[TestClient, LanceStore]:
    app = FastAPI()
    app.include_router(kb_router, prefix="/api")
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    # Open the vector table with a BARE model name — the exact server wiring.
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=_DIM, embedding_model=table_model)
    app.state.sqlite = sqlite
    app.state.lance = lance
    app.state.redactor = Redactor.from_yaml()
    app.state.embed_fn = _embed
    return TestClient(app), lance


def test_ingest_populates_vectors_when_table_model_differs_from_ref(tmp_path: Path) -> None:
    # Table declared with the bare model name (as the API server opens it).
    client, lance = _client(tmp_path, table_model="nomic-embed-text-v2-moe")
    doc = tmp_path / "sop.md"
    doc.write_text(
        "# VPN SOP\n\nIf authentication fails, verify RADIUS and the user account.\n",
        encoding="utf-8",
    )
    res = client.post("/api/kb/ingest", json={"paths": [str(doc)]})
    assert res.status_code == 200
    body = res.json()
    assert body["docs_succeeded"] == 1
    assert body["docs_failed"] == 0
    assert body["chunks_total"] >= 1
    # The real regression: vectors must be in the LanceDB table, not just FTS.
    assert lance.count() == body["chunks_total"]
