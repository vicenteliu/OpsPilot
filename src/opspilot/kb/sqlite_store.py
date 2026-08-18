"""SQLite-backed metadata store for the memory subsystem.

Owns two tables (full schema in ``docs/specs/memory/storage/sqlite-schema.sql``):

* ``kb_documents``  — one row per ingested source file
* ``kb_chunks``     — chunk-level metadata + ``vector_id`` link to LanceDB

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
import functools
import json
import secrets
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from ..dblock import lock_for

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


def _serialised[M: Callable[..., Any]](method: M) -> M:
    """Hold the store's lock for the whole method.

    Every method here drives one shared ``sqlite3.Connection`` — the API keeps a
    single store on ``app.state.sqlite`` and reaches it from the default
    multi-threaded executor, alongside four *other* stores on the same
    connection. The lock therefore belongs to the connection, not to this class
    (:mod:`opspilot.dblock`). Neither a statement sequence nor an ``execute`` →
    ``fetchone`` pair is atomic on that connection, and ``commit()`` is
    connection-scoped rather than thread-scoped. Unserialised, concurrent callers
    raise ``InterfaceError``, lose writes, and fail to read rows that are present
    (#166).

    The whole method is held, not each statement: locking individual calls would
    still let a read land between another thread's write and its commit.
    Reentrant because ``add_correction`` reads through ``get_chunk`` before
    writing.
    """

    @functools.wraps(method)
    def wrapper(self: SqliteStore, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(M, wrapper)


class SqliteStore:
    """Thin wrapper over a sqlite3 connection.

    Serialised: one lock covers every method that touches the connection. See
    :func:`_serialised`.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = lock_for(conn)

    @_serialised
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── KB documents ─────────────────────────────────────────────────

    @_serialised
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
            "valid_from": doc.get("valid_from"),
            "source_authority": doc.get("source_authority", "internal"),
        }

        # Updates in place rather than INSERT OR REPLACE: REPLACE deletes the
        # conflicting row first, and kb_chunks cascades from kb_documents — so
        # a plain metadata write (a title backfill, a re-classification) would
        # empty the document, and the chunks' own children (kb_conflicts,
        # kb_corrections) with it. See #144 and #157.
        self._conn.execute(
            """
            INSERT INTO kb_documents (
              id, source_path, source_url, title, classification,
              content_hash, version, ingested_at, last_modified, language,
              tags_json, namespace, chunk_strategy, chunk_count,
              embedding_model, embedding_dim, redaction_passed,
              redaction_rules_version, license, extensions_json,
              valid_from, source_authority
            ) VALUES (
              :id, :source_path, :source_url, :title, :classification,
              :content_hash, :version, :ingested_at, :last_modified, :language,
              :tags_json, :namespace, :chunk_strategy, :chunk_count,
              :embedding_model, :embedding_dim, :redaction_passed,
              :redaction_rules_version, :license, :extensions_json,
              :valid_from, :source_authority
            )
            ON CONFLICT(id) DO UPDATE SET
              source_path = excluded.source_path,
              source_url = excluded.source_url,
              title = excluded.title,
              classification = excluded.classification,
              content_hash = excluded.content_hash,
              version = excluded.version,
              ingested_at = excluded.ingested_at,
              last_modified = excluded.last_modified,
              language = excluded.language,
              tags_json = excluded.tags_json,
              namespace = excluded.namespace,
              chunk_strategy = excluded.chunk_strategy,
              chunk_count = excluded.chunk_count,
              embedding_model = excluded.embedding_model,
              embedding_dim = excluded.embedding_dim,
              redaction_passed = excluded.redaction_passed,
              redaction_rules_version = excluded.redaction_rules_version,
              license = excluded.license,
              extensions_json = excluded.extensions_json,
              valid_from = excluded.valid_from,
              source_authority = excluded.source_authority
            """,
            row,
        )
        self._conn.commit()

    @_serialised
    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM kb_documents WHERE id = ?", (doc_id,))
        r = cur.fetchone()
        if r is None:
            return None
        return _row_to_dict_with_json(r, json_fields=("tags_json", "extensions_json"))

    # ── KB chunks ────────────────────────────────────────────────────

    @_serialised
    def upsert_chunks(self, chunks: Iterable[dict[str, Any]]) -> int:
        """Batch-insert chunks. Returns number of rows written.

        Wraps the loop in a single transaction and updates an existing
        chunk in place.

        Deliberately not ``INSERT OR REPLACE``: REPLACE deletes the row
        before reinserting it, and both ``kb_conflicts`` (either side) and
        ``kb_corrections`` cascade from ``kb_chunks`` — so re-writing an
        unchanged chunk would discard the human decisions attached to it.
        See #157.
        """
        rows = [_chunk_dict_to_row(c) for c in chunks]
        if not rows:
            return 0
        self._conn.executemany(
            """
            INSERT INTO kb_chunks (
              id, document_id, seq, content, content_artifact_id,
              content_hash, char_start, char_end, line_start, line_end,
              heading_path_json, anchor, token_count, embedding_model,
              vector_id, namespace, classification, language, tags_json,
              valid_from, superseded_by
            ) VALUES (
              :id, :document_id, :seq, :content, :content_artifact_id,
              :content_hash, :char_start, :char_end, :line_start, :line_end,
              :heading_path_json, :anchor, :token_count, :embedding_model,
              :vector_id, :namespace, :classification, :language, :tags_json,
              :valid_from, :superseded_by
            )
            ON CONFLICT(id) DO UPDATE SET
              document_id = excluded.document_id,
              seq = excluded.seq,
              content = excluded.content,
              content_artifact_id = excluded.content_artifact_id,
              content_hash = excluded.content_hash,
              char_start = excluded.char_start,
              char_end = excluded.char_end,
              line_start = excluded.line_start,
              line_end = excluded.line_end,
              heading_path_json = excluded.heading_path_json,
              anchor = excluded.anchor,
              token_count = excluded.token_count,
              embedding_model = excluded.embedding_model,
              vector_id = excluded.vector_id,
              namespace = excluded.namespace,
              classification = excluded.classification,
              language = excluded.language,
              tags_json = excluded.tags_json,
              valid_from = excluded.valid_from,
              superseded_by = excluded.superseded_by
            """,
            rows,
        )
        self._reapply_corrections([str(r["id"]) for r in rows])
        self._conn.commit()
        return len(rows)

    def _reapply_corrections(self, chunk_ids: Sequence[str]) -> None:
        """Re-assert the newest correction on any chunk that carries one.

        A **Correction** overwrites a chunk's content in place while keeping
        its id. Chunk ids are content-addressed, so a re-ingest that produces
        the same id has produced the *same source text* — the text the
        correction was made against — and writing it back would silently
        revert the correction while its record still claimed to be in force.
        A KB that reports a correction it is not serving is worse than one
        that lost it outright.

        A changed source yields a different id, so nothing is re-applied
        there: that correction was about text which no longer exists, and the
        superseded chunk is removed by :meth:`delete_chunks_not_in`.

        See #157 and ADR-0023.
        """
        if not chunk_ids:
            return
        placeholders = ",".join("?" * len(chunk_ids))
        # created_at is millisecond-resolution, so two corrections written in
        # the same millisecond would tie and "newest" would be undefined.
        # rowid breaks it: kb_corrections is append-only, so insertion order
        # is a total order on the same instant.
        cur = self._conn.execute(
            f"""SELECT chunk_id, new_content FROM (
                    SELECT chunk_id, new_content,
                           ROW_NUMBER() OVER (
                               PARTITION BY chunk_id
                               ORDER BY created_at DESC, rowid DESC
                           ) AS rn
                    FROM kb_corrections
                    WHERE chunk_id IN ({placeholders})
                ) WHERE rn = 1""",  # noqa: S608
            tuple(chunk_ids),
        )
        latest = [(r["new_content"], r["chunk_id"]) for r in cur.fetchall()]
        if latest:
            self._conn.executemany("UPDATE kb_chunks SET content=? WHERE id=?", latest)

    @_serialised
    def delete_chunks_not_in(self, document_id: str, keep_ids: Iterable[str]) -> int:
        """Drop the document's chunks that are not in ``keep_ids``.

        Callers that rewrite a document's whole chunk set need the stale
        ones gone. That used to happen implicitly, as a cascade of the
        ``INSERT OR REPLACE`` in :meth:`upsert_document` — which also took
        the *surviving* chunks and their conflicts and corrections with it
        (#144, #157). The removal is explicit now, and scoped to chunks the
        new set no longer contains.

        A genuinely stale chunk's conflicts and corrections still cascade
        away with it, which is correct: chunk ids are content-addressed, so
        a chunk absent from the new set holds text that no longer exists.

        Returns the number of chunks removed.

        Note: this clears SQLite only. LanceDB vectors for the removed
        chunks are the caller's problem — see :meth:`LanceStore.delete_by_vector_ids`.
        """
        keep = list(keep_ids)
        placeholders = ",".join("?" * len(keep))
        sql = f"DELETE FROM kb_chunks WHERE document_id = ? AND id NOT IN ({placeholders})"  # noqa: S608
        cur = (
            self._conn.execute(sql, (document_id, *keep))
            if keep
            else self._conn.execute("DELETE FROM kb_chunks WHERE document_id = ?", (document_id,))
        )
        self._conn.commit()
        return cur.rowcount

    @_serialised
    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM kb_chunks WHERE id = ?", (chunk_id,))
        r = cur.fetchone()
        if r is None:
            return None
        return _row_to_dict_with_json(r, json_fields=("heading_path_json", "tags_json"))

    @_serialised
    def get_chunks_by_document_id(self, doc_id: str) -> list[dict[str, Any]]:
        """Return all chunks for *doc_id*, ordered by ``seq``."""
        cur = self._conn.execute(
            "SELECT * FROM kb_chunks WHERE document_id = ? ORDER BY seq",
            (doc_id,),
        )
        return [
            _row_to_dict_with_json(r, json_fields=("heading_path_json", "tags_json"))
            for r in cur.fetchall()
        ]

    @_serialised
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

    @_serialised
    def fts_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        namespace: str | None = None,
        classification: str | None = None,
        exclude_superseded: bool = True,
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
        if exclude_superseded:
            sql.append("AND c.superseded_by IS NULL")
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

    # ── KB conflicts ─────────────────────────────────────────────────

    @_serialised
    def upsert_conflict(self, conflict: dict[str, Any]) -> None:
        """Record a detected conflict; re-detecting the same id is a no-op.

        ``ON CONFLICT(id) DO NOTHING`` rather than ``INSERT OR IGNORE``:
        IGNORE also swallows CHECK and NOT NULL violations, so a mistyped
        ``conflict_type`` wrote nothing and reported success — the KB would
        look clean while holding contradictory content. Only a duplicate id
        is a no-op now; anything else raises. See #143.
        """
        self._conn.execute(
            """
            INSERT INTO kb_conflicts (
              id, chunk_a_id, chunk_b_id, doc_a_id, doc_b_id,
              conflict_type, similarity, status, detected_at
            ) VALUES (
              :id, :chunk_a_id, :chunk_b_id, :doc_a_id, :doc_b_id,
              :conflict_type, :similarity, :status, :detected_at
            )
            ON CONFLICT(id) DO NOTHING
            """,
            conflict,
        )
        self._conn.commit()

    @_serialised
    def get_conflict(self, conflict_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM kb_conflicts WHERE id = ?", (conflict_id,))
        r = cur.fetchone()
        return dict(r) if r else None

    @_serialised
    def list_conflicts(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return conflicts enriched with document titles."""
        where = "WHERE c.status = ?" if status else ""
        params: tuple[Any, ...] = (status, limit) if status else (limit,)
        cur = self._conn.execute(
            f"""
            SELECT c.*,
                   da.title AS doc_a_title, da.valid_from AS doc_a_valid_from,
                   db.title AS doc_b_title, db.valid_from AS doc_b_valid_from,
                   ca.content AS chunk_a_content, cb.content AS chunk_b_content
            FROM kb_conflicts c
            JOIN kb_documents da ON da.id = c.doc_a_id
            JOIN kb_documents db ON db.id = c.doc_b_id
            LEFT JOIN kb_chunks ca ON ca.id = c.chunk_a_id
            LEFT JOIN kb_chunks cb ON cb.id = c.chunk_b_id
            {where}
            ORDER BY c.detected_at DESC
            LIMIT ?
            """,
            params,
        )
        return [dict(r) for r in cur.fetchall()]

    @_serialised
    def update_conflict_status(
        self,
        conflict_id: str,
        *,
        status: str,
        resolved_by: str,
        resolved_at: str,
        resolution_note: str = "",
    ) -> None:
        self._conn.execute(
            """
            UPDATE kb_conflicts
            SET status=?, resolved_by=?, resolved_at=?, resolution_note=?
            WHERE id=?
            """,
            (status, resolved_by, resolved_at, resolution_note, conflict_id),
        )
        self._conn.commit()

    @_serialised
    def mark_chunk_superseded(self, chunk_id: str, *, superseded_by: str) -> None:
        self._conn.execute(
            "UPDATE kb_chunks SET superseded_by=? WHERE id=?",
            (superseded_by, chunk_id),
        )
        self._conn.commit()

    @_serialised
    def count_open_conflicts(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM kb_conflicts WHERE status='open'")
        return int(cur.fetchone()[0])

    @_serialised
    def get_docs_with_open_conflicts(self, doc_ids: list[str]) -> set[str]:
        """Return the subset of *doc_ids* that have at least one open conflict."""
        if not doc_ids:
            return set()
        placeholders = ",".join("?" * len(doc_ids))
        cur = self._conn.execute(
            f"SELECT DISTINCT doc_a_id AS doc_id FROM kb_conflicts "
            f"WHERE status='open' AND doc_a_id IN ({placeholders}) "
            f"UNION "
            f"SELECT DISTINCT doc_b_id FROM kb_conflicts "
            f"WHERE status='open' AND doc_b_id IN ({placeholders})",
            tuple(doc_ids) * 2,
        )
        return {str(r["doc_id"]) for r in cur.fetchall()}

    @_serialised
    def get_source_authorities(self, doc_ids: list[str]) -> dict[str, str]:
        """Return ``{doc_id: source_authority}`` for the given doc IDs."""
        if not doc_ids:
            return {}
        placeholders = ",".join("?" * len(doc_ids))
        cur = self._conn.execute(
            f"SELECT id, source_authority FROM kb_documents WHERE id IN ({placeholders})",
            tuple(doc_ids),
        )
        return {str(r["id"]): str(r["source_authority"]) for r in cur.fetchall()}

    @_serialised
    def get_superseded_chunk_ids(self, chunk_ids: list[str]) -> set[str]:
        """Return the subset of *chunk_ids* where ``superseded_by IS NOT NULL``."""
        if not chunk_ids:
            return set()
        placeholders = ",".join("?" * len(chunk_ids))
        cur = self._conn.execute(
            f"SELECT id FROM kb_chunks WHERE id IN ({placeholders}) AND superseded_by IS NOT NULL",
            tuple(chunk_ids),
        )
        return {str(r["id"]) for r in cur.fetchall()}

    # ── kb_corrections ───────────────────────────────────────────────

    @_serialised
    def add_correction(
        self,
        chunk_id: str,
        corrected_by: str,
        reason: str,
        new_content: str,
    ) -> str:
        """Record an inline correction and update the chunk content.

        Returns the new ``corr_id``.  Raises ``KeyError`` if the chunk
        does not exist.
        """
        from ..timeutil import now_rfc3339

        row = self.get_chunk(chunk_id)
        if row is None:
            raise KeyError(f"Chunk {chunk_id!r} not found")
        old_content = str(row.get("content") or "")
        corr_id = "corr_" + secrets.token_hex(4)
        now = now_rfc3339()
        self._conn.execute(
            """INSERT INTO kb_corrections
               (id, chunk_id, corrected_by, reason, old_content, new_content, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (corr_id, chunk_id, corrected_by, reason, old_content, new_content, now),
        )
        self._conn.execute(
            "UPDATE kb_chunks SET content=? WHERE id=?",
            (new_content, chunk_id),
        )
        self._conn.commit()
        return corr_id

    @_serialised
    def list_corrections(
        self,
        chunk_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return correction records, newest first.

        Optionally filtered to a single *chunk_id*.
        """
        if chunk_id:
            cur = self._conn.execute(
                "SELECT * FROM kb_corrections WHERE chunk_id=? ORDER BY created_at DESC LIMIT ?",
                (chunk_id, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM kb_corrections ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in cur.fetchall()]

    @_serialised
    def kb_stats(self) -> dict[str, int]:
        """Return aggregate KB health counts."""
        rows = self._conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM kb_documents)                       AS docs_total,
              (SELECT COUNT(*) FROM kb_chunks)                          AS chunks_total,
              (SELECT COUNT(*) FROM kb_conflicts WHERE status = 'open') AS open_conflicts,
              (SELECT COUNT(*) FROM kb_corrections)                     AS corrections_total
            """
        ).fetchone()
        return {
            "docs_total": int(rows["docs_total"]),
            "chunks_total": int(rows["chunks_total"]),
            "open_conflicts": int(rows["open_conflicts"]),
            "corrections_total": int(rows["corrections_total"]),
        }


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
        "valid_from": c.get("valid_from"),
        "superseded_by": c.get("superseded_by"),
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
