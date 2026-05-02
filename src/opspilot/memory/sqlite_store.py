"""SQLite-backed metadata store for the memory subsystem.

Owns three tables (full schema in ``memory/storage/sqlite-schema.sql``):

* ``kb_documents``  — one row per ingested source file
* ``kb_chunks``     — chunk-level metadata + ``vector_id`` link to LanceDB
* ``memory_records`` — mid-term memory rows (minimal CRUD in PR-4; PR-6
  layers session-driven writes on top)

Plus an FTS5 keyword index over ``kb_chunks`` (BM25, ``unicode61``
tokenizer with diacritic folding). Vector bodies live in LanceDB (see
``lance_store.py``); the contract between the two stores is the
1:1 ``kb_chunks.vector_id ↔ chunks.vector_id`` mapping.

Design notes
------------
* All inputs are strict pydantic-ish models — we accept dicts at the
  boundary and rely on SQLite's ``CHECK`` constraints to enforce shape.
* Batch writes are wrapped in transactions to keep ingestion cheap.
* All content **must already be redacted** (``redaction_passed=1``);
  the schema enforces this with a CHECK constraint, but the store also
  raises a friendlier ``ValueError`` upfront so callers get an early
  signal during ingestion debugging.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

# ── Public dataclasses (DB-row mirrors) ──────────────────────────────


@dataclass(frozen=True)
class FtsHit:
    """Single FTS5 result row.

    ``score`` is the **negated** ``bm25()`` value, i.e. higher = more
    relevant (SQLite's ``bm25()`` returns lower-is-better; we flip the
    sign here so callers can sort descending without thinking).
    """

    chunk_id: str
    score: float
    document_id: str
    namespace: str


# ── Store class ───────────────────────────────────────────────────────


class SqliteStore:
    """Thin wrapper over a sqlite3 connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── KB documents ─────────────────────────────────────────────────

    def upsert_document(self, doc: dict[str, Any]) -> None:
        """Insert (or replace by id) a single ``kb_documents`` row.

        Accepts the JSON-shaped dict from ``doc-meta.json`` — handles
        the ``tags``/``extensions`` → ``tags_json``/``extensions_json``
        and ``redaction_passed`` bool→int conversions.
        """
        if not doc.get("redaction_passed", False):
            raise ValueError(
                f"Document {doc.get('id')} has redaction_passed=False; "
                "all KB content must be redacted before persistence."
            )

        row = {
            "id": doc["id"],
            "source_path": doc["source_path"],
            "source_url": doc.get("source_url"),
            "title": doc["title"],
            "classification": doc["classification"],
            "content_hash": doc["content_hash"],
            "version": doc.get("version"),
            "ingested_at": doc["ingested_at"],
            "last_modified": doc.get("last_modified"),
            "language": doc["language"],
            "tags_json": json.dumps(doc.get("tags", []), ensure_ascii=False),
            "namespace": doc["namespace"],
            "chunk_strategy": doc["chunk_strategy"],
            "chunk_count": int(doc.get("chunk_count", 0)),
            "embedding_model": doc["embedding_model"],
            "embedding_dim": int(doc["embedding_dim"]),
            "redaction_passed": 1,
            "redaction_rules_version": doc.get("redaction_rules_version"),
            "license": doc.get("license"),
            "extensions_json": json.dumps(doc.get("extensions", {}), ensure_ascii=False),
        }

        self._conn.execute(
            """
            INSERT OR REPLACE INTO kb_documents (
              id, source_path, source_url, title, classification,
              content_hash, version, ingested_at, last_modified, language,
              tags_json, namespace, chunk_strategy, chunk_count,
              embedding_model, embedding_dim, redaction_passed,
              redaction_rules_version, license, extensions_json
            ) VALUES (
              :id, :source_path, :source_url, :title, :classification,
              :content_hash, :version, :ingested_at, :last_modified, :language,
              :tags_json, :namespace, :chunk_strategy, :chunk_count,
              :embedding_model, :embedding_dim, :redaction_passed,
              :redaction_rules_version, :license, :extensions_json
            )
            """,
            row,
        )
        self._conn.commit()

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM kb_documents WHERE id = ?", (doc_id,))
        r = cur.fetchone()
        if r is None:
            return None
        return _row_to_dict_with_json(r, json_fields=("tags_json", "extensions_json"))

    # ── KB chunks ────────────────────────────────────────────────────

    def upsert_chunks(self, chunks: Iterable[dict[str, Any]]) -> int:
        """Batch-insert chunks. Returns number of rows written.

        Wraps the loop in a single transaction. ``INSERT OR REPLACE`` so
        re-ingesting the same chunk_id updates in place.
        """
        rows = [_chunk_dict_to_row(c) for c in chunks]
        if not rows:
            return 0
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO kb_chunks (
              id, document_id, seq, content, content_artifact_id,
              content_hash, char_start, char_end, line_start, line_end,
              heading_path_json, anchor, token_count, embedding_model,
              vector_id, namespace, classification, language, tags_json
            ) VALUES (
              :id, :document_id, :seq, :content, :content_artifact_id,
              :content_hash, :char_start, :char_end, :line_start, :line_end,
              :heading_path_json, :anchor, :token_count, :embedding_model,
              :vector_id, :namespace, :classification, :language, :tags_json
            )
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM kb_chunks WHERE id = ?", (chunk_id,))
        r = cur.fetchone()
        if r is None:
            return None
        return _row_to_dict_with_json(r, json_fields=("heading_path_json", "tags_json"))

    def get_chunks_by_vector_ids(self, vector_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Fetch chunks for a set of LanceDB vector_ids; returns {vector_id: row}.

        Used by ``retrieval`` to hydrate ANN hits with their text content.
        """
        if not vector_ids:
            return {}
        # SQLite parameter limit is 999 by default — chunk if that ever
        # bites, but for top_k <= 50 we're nowhere near that.
        placeholders = ",".join("?" for _ in vector_ids)
        cur = self._conn.execute(
            f"SELECT * FROM kb_chunks WHERE vector_id IN ({placeholders})",
            tuple(vector_ids),
        )
        out: dict[str, dict[str, Any]] = {}
        for r in cur.fetchall():
            row = _row_to_dict_with_json(r, json_fields=("heading_path_json", "tags_json"))
            out[row["vector_id"]] = row
        return out

    # ── FTS5 keyword search ──────────────────────────────────────────

    def fts_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        namespace: str | None = None,
        classification: str | None = None,
    ) -> list[FtsHit]:
        """Run a BM25 keyword query over ``kb_chunks_fts``.

        ``query`` is passed verbatim to FTS5 — caller is responsible for
        any prefix/phrase syntax. We add a NULL guard for empty queries
        because FTS5 raises on those.
        """
        q = (query or "").strip()
        if not q:
            return []

        sql = [
            "SELECT c.id AS chunk_id, c.document_id AS document_id,",
            "       c.namespace AS namespace, bm25(kb_chunks_fts) AS score",
            "FROM kb_chunks_fts JOIN kb_chunks c ON c.rowid = kb_chunks_fts.rowid",
            "WHERE kb_chunks_fts MATCH ?",
        ]
        params: list[Any] = [q]
        if namespace:
            sql.append("AND c.namespace = ?")
            params.append(namespace)
        if classification:
            sql.append("AND c.classification = ?")
            params.append(classification)
        sql.append("ORDER BY score ASC LIMIT ?")
        params.append(top_k)

        cur = self._conn.execute(" ".join(sql), tuple(params))
        # FTS5 bm25() is lower-is-better; flip sign so callers get
        # higher-is-better scores (matching the convention used for
        # vector cosine_similarity downstream).
        return [
            FtsHit(
                chunk_id=r["chunk_id"],
                score=-float(r["score"]),
                document_id=r["document_id"],
                namespace=r["namespace"],
            )
            for r in cur.fetchall()
        ]

    # ── memory_records (D3 — minimal CRUD) ───────────────────────────

    def write_memory(self, record: dict[str, Any]) -> None:
        """Insert (or replace by id) a single ``memory_records`` row.

        PR-4 only ships write/get; PR-6 layers session-driven updates
        and TTL sweeps on top.
        """
        if not record.get("redacted", False):
            raise ValueError(
                f"Memory record {record.get('id')} has redacted=False; "
                "all memory content must be redacted before persistence."
            )

        row = {
            "id": record["id"],
            "type": record["type"],
            "scope": record["scope"],
            "title": record["title"],
            "body": record["body"],
            "tags_json": json.dumps(record.get("tags", []), ensure_ascii=False),
            "source_origin": record["source_origin"],
            "source_session_id": record.get("source_session_id"),
            "source_trace_seq": record.get("source_trace_seq"),
            "source_document_id": record.get("source_document_id"),
            "source_url": record.get("source_url"),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "valid_until": record.get("valid_until"),
            "confidence": record["confidence"],
            "redacted": 1,
            "redaction_rules_version": record.get("redaction_rules_version"),
            "labels_json": json.dumps(record.get("labels", {}), ensure_ascii=False),
            "extensions_json": json.dumps(record.get("extensions", {}), ensure_ascii=False),
        }
        self._conn.execute(
            """
            INSERT OR REPLACE INTO memory_records (
              id, type, scope, title, body, tags_json, source_origin,
              source_session_id, source_trace_seq, source_document_id,
              source_url, created_at, updated_at, valid_until, confidence,
              redacted, redaction_rules_version, labels_json, extensions_json
            ) VALUES (
              :id, :type, :scope, :title, :body, :tags_json, :source_origin,
              :source_session_id, :source_trace_seq, :source_document_id,
              :source_url, :created_at, :updated_at, :valid_until, :confidence,
              :redacted, :redaction_rules_version, :labels_json, :extensions_json
            )
            """,
            row,
        )
        self._conn.commit()

    def get_memory(self, mem_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM memory_records WHERE id = ?", (mem_id,))
        r = cur.fetchone()
        if r is None:
            return None
        return _row_to_dict_with_json(
            r, json_fields=("tags_json", "labels_json", "extensions_json")
        )


# ── Helpers ───────────────────────────────────────────────────────────


def _chunk_dict_to_row(c: dict[str, Any]) -> dict[str, Any]:
    """Translate the JSON chunk shape into a ``kb_chunks`` row dict.

    The JSON shape (from chunks.jsonl / kb-chunk.schema.json) has
    ``heading_path: list[str]`` and a nested ``metadata: {...}`` block;
    the SQL row uses ``heading_path_json`` plus flat columns. We do that
    flattening here so callers can pass the JSON dict unchanged.
    """
    md = c.get("metadata") or {}
    return {
        "id": c["id"],
        "document_id": c["document_id"],
        "seq": int(c["seq"]),
        "content": c.get("content"),
        "content_artifact_id": c.get("content_artifact_id"),
        "content_hash": c["content_hash"],
        "char_start": int(c["char_start"]),
        "char_end": int(c["char_end"]),
        "line_start": int(c["line_start"]),
        "line_end": int(c["line_end"]),
        "heading_path_json": json.dumps(c.get("heading_path", []), ensure_ascii=False),
        "anchor": c.get("anchor"),
        "token_count": c.get("token_count"),
        "embedding_model": c["embedding_model"],
        "vector_id": c["vector_id"],
        "namespace": md.get("namespace") or c.get("namespace"),
        "classification": md.get("classification") or c.get("classification"),
        "language": md.get("language") or c.get("language"),
        "tags_json": json.dumps(md.get("tags") or c.get("tags") or [], ensure_ascii=False),
    }


def _row_to_dict_with_json(row: sqlite3.Row, *, json_fields: tuple[str, ...]) -> dict[str, Any]:
    """sqlite3.Row → dict, decoding the listed ``*_json`` text columns."""
    # `for k in row.keys()` is required: iterating sqlite3.Row directly
    # yields values, not column names — unlike a regular dict.
    out: dict[str, Any] = {k: row[k] for k in row.keys()}  # noqa: SIM118
    for f in json_fields:
        if f in out and isinstance(out[f], str):
            # Leave raw text if somehow malformed — surfaces issues without
            # corrupting the read.
            with contextlib.suppress(json.JSONDecodeError):
                out[f] = json.loads(out[f])
    return out
