"""LanceDB-backed vector store for KB chunks.

Owns the long-term vector body. SQLite owns the metadata; LanceDB owns the
embeddings + the bare minimum of filter columns. The two are joined via
``vector_id`` which is the LanceDB primary key and the ``kb_chunks.vector_id``
foreign reference (see ``docs/specs/memory/storage/lancedb-schema.md``).

Per-KB layout::

    <root>/lancedb/<kb_id>.lance/

with one ``chunks`` table per dataset. PR-4 ships a single dataset (the
default ``opspilot:public-kb``); table-per-namespace splitting is a future
optimisation.

PR-4 doesn't build the IVF_PQ ANN index — the test KB has 3 vectors so
brute-force scan is correct and faster than indexing. ``build_ann_index``
is exposed so PR-5 / PR-7 can call it after a large ingest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

# 3.10/3.11-compat alias for `datetime.UTC` (added in 3.11). Project targets
# 3.12 in production but the dev sandbox runs 3.10, so we keep the alias.
UTC = timezone.utc  # noqa: UP017

# Spec column name (per docs/specs/memory/storage/lancedb-schema.md).
VECTOR_COLUMN: str = "embedding"
TABLE_NAME: str = "chunks"

# Distance metric — cosine is what the spec mandates and is the standard
# choice for sentence-embedding models. Set on every search() call.
METRIC: str = "cosine"


@dataclass(frozen=True)
class VectorRecord:
    """One row in the LanceDB ``chunks`` table.

    ``embedding`` length must match the table's fixed dim — enforced by
    PyArrow on insert.
    """

    vector_id: str
    embedding: Sequence[float]
    document_id: str
    chunk_id: str
    namespace: str
    classification: str
    language: str
    tags: Sequence[str]
    embedding_model: str

    def to_arrow_record(self) -> dict[str, Any]:
        """Shape expected by ``table.add`` / ``merge_insert`` / PyArrow.

        ``created_at`` is truncated to millisecond resolution to match the
        schema's ``timestamp[ms, tz=UTC]`` — PyArrow refuses lossy us→ms
        conversion.
        """
        now = datetime.now(UTC)
        now_ms = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        return {
            "vector_id": self.vector_id,
            "embedding": list(self.embedding),
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "namespace": self.namespace,
            "classification": self.classification,
            "language": self.language,
            "tags": list(self.tags),
            "embedding_model": self.embedding_model,
            "created_at": now_ms,
        }


@dataclass(frozen=True)
class AnnHit:
    """Single ANN search result.

    ``score`` follows the higher-is-better convention. For cosine,
    LanceDB returns ``_distance = 1 - cos_sim``, so we convert to
    ``cos_sim = 1 - _distance`` here. Range: ``[-1, 1]``.
    """

    vector_id: str
    score: float
    chunk_id: str
    document_id: str
    namespace: str


# ── Store class ───────────────────────────────────────────────────────


class LanceStore:
    """Per-KB LanceDB dataset with a single ``chunks`` table.

    Construction is split into two paths:

    * :meth:`open_or_create` — usual entry point; opens the dataset and
      creates the table on first use.
    * :meth:`__init__` — internal; takes an already-opened table.

    Always pin ``embedding_model`` + ``dim`` at table creation. Mixing
    embedding spaces in the same table breaks ANN; the caller must build
    a new table when switching models (per
    ``docs/specs/memory/storage/lancedb-schema.md`` design principle #4).
    """

    def __init__(
        self,
        *,
        db: lancedb.DBConnection,
        table: lancedb.table.Table,
        dim: int,
        embedding_model: str,
    ) -> None:
        self._db = db
        self._table = table
        self.dim = dim
        self.embedding_model = embedding_model

    # ── Constructors ─────────────────────────────────────────────────

    @classmethod
    def open_or_create(
        cls,
        path: Path,
        *,
        dim: int,
        embedding_model: str,
    ) -> LanceStore:
        """Open the LanceDB dataset at ``path``; create ``chunks`` table if absent."""
        path.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(path))

        if TABLE_NAME in db.table_names():
            table = db.open_table(TABLE_NAME)
            existing_dim = _detect_dim(table)
            if existing_dim != dim:
                raise ValueError(
                    f"LanceDB table '{TABLE_NAME}' at {path} was created with "
                    f"dim={existing_dim}; refusing to mix with dim={dim}. "
                    "Switching embedding models requires a new dataset."
                )
        else:
            schema = _build_schema(dim)
            table = db.create_table(TABLE_NAME, schema=schema)

        return cls(db=db, table=table, dim=dim, embedding_model=embedding_model)

    # ── Mutations ────────────────────────────────────────────────────

    def upsert_vectors(self, records: Sequence[VectorRecord]) -> int:
        """Insert or update by ``vector_id``. Returns row count written."""
        if not records:
            return 0

        for r in records:
            if len(r.embedding) != self.dim:
                raise ValueError(
                    f"vector_id={r.vector_id} embedding has length "
                    f"{len(r.embedding)}; expected {self.dim}"
                )
            if r.embedding_model != self.embedding_model:
                raise ValueError(
                    f"vector_id={r.vector_id} embedding_model="
                    f"{r.embedding_model!r}; expected {self.embedding_model!r}"
                )

        rows = [r.to_arrow_record() for r in records]
        # merge_insert is the upsert idiom in LanceDB 0.5.x.
        (
            self._table.merge_insert(on="vector_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(rows)
        )
        return len(rows)

    def delete_by_vector_ids(self, vector_ids: Sequence[str]) -> None:
        if not vector_ids:
            return
        # SQL-quoted IN list. vector_ids are sha8 hex prefixes so no escaping
        # concerns; we still strip quotes defensively.
        sanitized = [v.replace("'", "''") for v in vector_ids]
        in_list = ",".join(f"'{v}'" for v in sanitized)
        self._table.delete(f"vector_id IN ({in_list})")

    def count(self) -> int:
        # lancedb is untyped at the package level; count_rows returns int.
        return int(self._table.count_rows())

    # ── ANN search ───────────────────────────────────────────────────

    def ann_search(
        self,
        query_vec: Sequence[float],
        *,
        top_k: int = 10,
        namespace: str | None = None,
        classification: str | None = None,
    ) -> list[AnnHit]:
        if len(query_vec) != self.dim:
            raise ValueError(f"query vector has length {len(query_vec)}; expected {self.dim}")

        search = (
            self._table.search(list(query_vec), vector_column_name=VECTOR_COLUMN)
            .metric(METRIC)
            .limit(top_k)
        )
        # Combine filter clauses with AND. ``where()`` takes a SQL-ish predicate.
        clauses: list[str] = []
        if namespace:
            clauses.append(f"namespace = '{namespace}'")
        if classification:
            clauses.append(f"classification = '{classification}'")
        if clauses:
            search = search.where(" AND ".join(clauses))

        rows = search.to_list()
        return [
            AnnHit(
                vector_id=r["vector_id"],
                # cosine: distance = 1 - cosine_similarity → flip back
                score=1.0 - float(r["_distance"]),
                chunk_id=r["chunk_id"],
                document_id=r["document_id"],
                namespace=r["namespace"],
            )
            for r in rows
        ]

    # ── ANN index management ─────────────────────────────────────────

    def build_ann_index(
        self,
        *,
        num_partitions: int = 64,
        num_sub_vectors: int = 96,
    ) -> None:
        """Build IVF_PQ index on the ``embedding`` column.

        Skipped under PR-4's tiny test KB (n=3 → brute force is faster).
        Call after a large batch ingest in PR-5+.
        """
        self._table.create_index(
            metric=METRIC,
            num_partitions=num_partitions,
            num_sub_vectors=num_sub_vectors,
            vector_column_name=VECTOR_COLUMN,
        )


# ── Schema helpers ────────────────────────────────────────────────────


def _build_schema(dim: int) -> pa.Schema:
    """Per docs/specs/memory/storage/lancedb-schema.md primary-table spec."""
    return pa.schema(
        [
            pa.field("vector_id", pa.string(), nullable=False),
            pa.field(
                VECTOR_COLUMN,
                pa.list_(pa.float32(), dim),
                nullable=False,
            ),
            pa.field("document_id", pa.string(), nullable=False),
            pa.field("chunk_id", pa.string(), nullable=False),
            pa.field("namespace", pa.string(), nullable=False),
            pa.field("classification", pa.string(), nullable=False),
            pa.field("language", pa.string(), nullable=False),
            pa.field("tags", pa.list_(pa.string()), nullable=False),
            pa.field("embedding_model", pa.string(), nullable=False),
            pa.field(
                "created_at",
                pa.timestamp("ms", tz="UTC"),
                nullable=False,
            ),
        ]
    )


def _detect_dim(table: lancedb.table.Table) -> int:
    """Read embedding fixed-list size from the table's PyArrow schema."""
    field = table.schema.field(VECTOR_COLUMN)
    if not pa.types.is_fixed_size_list(field.type):
        raise TypeError(f"expected '{VECTOR_COLUMN}' to be fixed_size_list; got {field.type}")
    return int(field.type.list_size)
