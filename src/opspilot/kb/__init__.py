"""Memory subsystem.

* PR-2: markdown chunker
* PR-3: Ollama provider (in ``providers/``, not here)
* PR-4: SQLite + LanceDB stores + hybrid retrieval
* PR-5: markitdown adapter + ingestion pipeline ← current
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
