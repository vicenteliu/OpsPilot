"""Load a frozen KB fixture (chunks.jsonl + doc-meta.json) into the live stores.

Why a separate path from :mod:`opspilot.memory.ingestion`?

The ingestion pipeline (markitdown → redact → chunk → embed → upsert) is the
*real-user* code path. Spec-example KB fixtures
(``examples/scn_ticket_summary_zh/kb/``) are **frozen ground truth**: every
chunk_id, document_id, content_hash, and line range is hand-authored to
match the rest of the spec — golden assertions, retrieval response samples,
checks.md crosswalk. Re-running the chunker on the same markdown produces
*different* chunk boundaries (PR-2's ``headings_then_size`` strategy
greedily merges below ``target_size_tokens``), which makes the spec-example
RAG evaluators permanently misalign.

This module bypasses the chunker entirely: it reads the JSONL+JSON pair as
authoritative and upserts them verbatim into SQLite + LanceDB. Callers
(``opspilot kb load-fixture`` CLI, ``make golden-kb``) get a deterministic
seed that is byte-identical to what the spec promises.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .lance_store import LanceStore, VectorRecord
from .sqlite_store import SqliteStore

EmbedFn = Callable[[str], list[float]]


@dataclass(frozen=True)
class KBLoadStats:
    """Outcome of one :func:`load_kb_fixture` call."""

    document_id: str
    chunk_count: int
    vector_count: int  # 0 when classification='restricted' (FTS-only)


def load_kb_fixture(
    *,
    sqlite: SqliteStore,
    lance: LanceStore,
    doc_meta_path: Path,
    chunks_jsonl_path: Path,
    embed_fn: EmbedFn,
) -> KBLoadStats:
    """Upsert a fixture KB pair into the live stores.

    Args:
        sqlite: open ``SqliteStore`` (call site decides DB location).
        lance:  open ``LanceStore`` matching ``embed_fn``'s output dim.
        doc_meta_path:    ``doc-meta.json`` (single document object).
        chunks_jsonl_path: ``chunks.jsonl`` (one chunk dict per line).
        embed_fn: maps a string → embedding list. Caller wires the
                  provider; we never import providers here.

    Returns:
        Stats useful for the CLI table renderer.
    """
    if not doc_meta_path.is_file():
        raise FileNotFoundError(f"doc-meta not found: {doc_meta_path}")
    if not chunks_jsonl_path.is_file():
        raise FileNotFoundError(f"chunks.jsonl not found: {chunks_jsonl_path}")

    # ── 1. Document ─────────────────────────────────────────────────────
    doc = json.loads(doc_meta_path.read_text(encoding="utf-8"))
    doc.pop("_comment", None)
    sqlite.upsert_document(doc)
    document_id = str(doc["id"])

    # ── 2. Chunks (sqlite) ──────────────────────────────────────────────
    chunks: list[dict[str, Any]] = []
    for line in chunks_jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        c.pop("_comment", None)
        chunks.append(c)
    sqlite.upsert_chunks(chunks)

    # ── 3. Vectors (lance) — one embed call per chunk ───────────────────
    # ``classification=restricted`` = FTS-only by design; skip embed to
    # keep parity with the ingestion pipeline (memory/ingestion.py D7).
    records: list[VectorRecord] = []
    for c in chunks:
        md = c.get("metadata") or {}
        classification = str(md.get("classification") or "internal")
        if classification == "restricted":
            continue
        vec = embed_fn(c["content"] or "")
        records.append(
            VectorRecord(
                vector_id=str(c["vector_id"]),
                embedding=vec,
                document_id=str(c["document_id"]),
                chunk_id=str(c["id"]),
                namespace=str(md.get("namespace") or "opspilot:public-kb"),
                classification=classification,
                language=str(md.get("language") or "und"),
                tags=list(md.get("tags") or []),
                # Always use the lance store's pinned embedding_model.
                # The fixture's `embedding_model` field is a spec
                # placeholder ("nomic-embed-text@2024-02"); what matters
                # at runtime is what embed_fn actually produced, which by
                # construction matches lance.embedding_model.
                embedding_model=lance.embedding_model,
            )
        )
    if records:
        lance.upsert_vectors(records)

    return KBLoadStats(
        document_id=document_id,
        chunk_count=len(chunks),
        vector_count=len(records),
    )
