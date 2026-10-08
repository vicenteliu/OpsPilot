"""The KB: ingested documents, chunked, stored and searched.

Not Memory. The KB holds what was ingested, built from the handbook and
other documents (ADR-0038); Memory holds the standing facts a person
admits, and reaches an answer on a path of its own (``opspilot.memory``,
ADR-0031).

* ``ingestion`` + ``markitdown_adapter``: discover → markdown → redact →
  chunk → embed → upsert
* ``chunker`` / ``tokenizer``: Rust hot paths, with a Python fallback
* ``sqlite_store`` (FTS5) + ``lance_store`` (vectors): the two stores
* ``retrieval``: hybrid search, fused by weighted RRF
* ``conflict``: chunk-level conflicts and how they were settled
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
    # PR-2
    "Chunk",
    "ChunkConfig",
    "chunk_markdown",
    # PR-4 — storage init
    "init_sqlite",
    "open_sqlite",
    # PR-4 — SQLite store
    "FtsHit",
    "SqliteStore",
    # PR-4 — Lance store
    "AnnHit",
    "LanceStore",
    "VectorRecord",
    # PR-4 — retrieval
    "DEFAULT_KEYWORD_WEIGHT",
    "DEFAULT_VECTOR_WEIGHT",
    "EmbedFn",
    "Hit",
    "RRF_K",
    "kb_search",
    # PR-5 — markitdown adapter
    "AdapterError",
    "AdapterResult",
    "to_markdown",
    # PR-5 — ingestion
    "FileResult",
    "HARD_FAIL_PLACEHOLDER_TYPES",
    "IngestConfig",
    "IngestStats",
    "IngestionError",
    "discover_files",
    "ingest",
]
