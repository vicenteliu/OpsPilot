"""The KB: ingested documents, chunked, stored and searched.

Not Memory. The KB holds what was ingested; Memory holds the standing facts a
person admits, and reaches an answer on a path of its own (``opspilot.memory``,
ADR-0031). ADR-0038 makes the SSC handbook the KB's single source and the KB a
build artifact. That build is not written yet: ``ingest`` takes whatever paths
it is given.

* ``ingestion`` + ``markitdown_adapter``: discover → markdown → redact →
  chunk → embed → upsert → conflict detection
* ``storage_init``: opens the SQLite file, applies the schema and its migrations
* ``sqlite_store`` (FTS5) + ``lance_store`` (vectors): the two stores
* ``retrieval``: hybrid search, fused by weighted RRF
* ``conflict``: chunk-level conflicts and how they were settled
* ``chunker``: a Rust hot path, with a Python fallback
* ``tokenizer``: a token counter (Rust, with a Python fallback) that nothing in
  ``src/`` calls today
* ``kb_loader``: frozen fixtures (``chunks.jsonl`` + ``doc-meta.json``)
"""

from .chunker import Chunk, ChunkConfig, chunk_markdown
from .ingestion import (
    HARD_FAIL_PLACEHOLDER_TYPES,
    FileResult,
    IngestConfig,
    IngestionError,
    IngestStats,
    discover_files,
    ingest,
)
from .lance_store import AnnHit, LanceStore, VectorRecord
from .markitdown_adapter import AdapterError, AdapterResult, to_markdown
from .retrieval import (
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_VECTOR_WEIGHT,
    RRF_K,
    EmbedFn,
    Hit,
    kb_search,
)
from .sqlite_store import FtsHit, SqliteStore
from .storage_init import init_sqlite, open_sqlite

__all__ = [
    # chunker
    "Chunk",
    "ChunkConfig",
    "chunk_markdown",
    # storage_init
    "init_sqlite",
    "open_sqlite",
    # sqlite_store
    "FtsHit",
    "SqliteStore",
    # lance_store
    "AnnHit",
    "LanceStore",
    "VectorRecord",
    # retrieval
    "DEFAULT_KEYWORD_WEIGHT",
    "DEFAULT_VECTOR_WEIGHT",
    "EmbedFn",
    "Hit",
    "RRF_K",
    "kb_search",
    # markitdown_adapter
    "AdapterError",
    "AdapterResult",
    "to_markdown",
    # ingestion
    "FileResult",
    "HARD_FAIL_PLACEHOLDER_TYPES",
    "IngestConfig",
    "IngestStats",
    "IngestionError",
    "discover_files",
    "ingest",
]
