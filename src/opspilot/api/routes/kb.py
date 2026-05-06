"""KB API routes: GET /api/kb/docs, POST /api/kb/ingest, GET /api/kb/search."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

router = APIRouter()


@router.get("/kb/docs")
async def list_docs(request: Request) -> dict[str, Any]:
    """List all ingested KB documents."""
    cfg = request.app.state.cfg
    db_path = cfg.home / "kb" / "sqlite.db"
    docs: list[dict[str, Any]] = []
    if db_path.exists():
        loop = asyncio.get_event_loop()

        def _read() -> list[dict[str, Any]]:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT id, title, language, chunk_count, namespace, ingested_at "
                "FROM kb_documents ORDER BY ingested_at DESC"
            )
            rows = [
                {
                    "doc_id": r["id"],
                    "title": r["title"] or "",
                    "language": r["language"] or "",
                    "chunk_count": r["chunk_count"],
                    "namespace": r["namespace"] or "",
                    "ingested_at": (r["ingested_at"] or "")[:19],
                }
                for r in cur.fetchall()
            ]
            conn.close()
            return rows

        docs = await loop.run_in_executor(None, _read)
    return {"docs": docs}


class IngestRequest(BaseModel):
    paths: list[str]
    kb_id: str = "opspilot:public-kb"
    namespace: str | None = None
    classification: str = "internal"


@router.post("/kb/ingest")
async def ingest_docs(body: IngestRequest, request: Request) -> dict[str, Any]:
    """Ingest one or more files into the KB."""
    state = request.app.state
    cfg = state.cfg

    from ...memory.ingestion import IngestConfig
    from ...memory.ingestion import ingest as run_ingest

    paths = [Path(p) for p in body.paths]
    ic = IngestConfig(
        kb_id=body.kb_id,
        namespace=body.namespace,
        classification=body.classification,
        embedding_model=f"ollama-local/{cfg.embed_model}@2026-04",
        embedding_dim=768,
    )

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        return run_ingest(
            paths,
            sqlite=state.sqlite,
            lance=state.lance,
            redactor=state.redactor,
            embed_fn=state.embed_fn,
            config=ic,
        )

    stats = await loop.run_in_executor(None, _run)

    return {
        "run_id": stats.run_id,
        "docs_succeeded": stats.docs_succeeded,
        "docs_failed": stats.docs_failed,
        "chunks_total": stats.chunks_total,
        "duration_ms": stats.duration_ms,
        "files": [
            {
                "source_path": str(fr.source_path),
                "document_id": fr.document_id,
                "chunks_written": fr.chunks_written,
                "error": fr.error,
            }
            for fr in stats.files
        ],
    }


@router.get("/kb/search")
async def search_kb(
    request: Request,
    q: str = Query(..., description="Search query"),
    top_k: int = Query(5, description="Max hits"),
    namespace: str | None = Query(None),
    classification: str | None = Query(None),
) -> dict[str, Any]:
    """Hybrid (FTS5 + ANN) search over the KB."""
    state = request.app.state

    from ...memory.retrieval import kb_search

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        return kb_search(
            q,
            sqlite=state.sqlite,
            lance=state.lance,
            embed_fn=state.embed_fn,
            top_k=top_k,
            namespace=namespace,
            classification=classification,
        )

    hits = await loop.run_in_executor(None, _run)

    return {
        "query": q,
        "hits": [
            {
                "chunk_id": h.chunk_id,
                "document_id": h.document_id,
                "score": h.score,
                "rank_vector": h.rank_vector,
                "rank_fts": h.rank_fts,
                "content": (h.content or "")[:500],
            }
            for h in hits
        ],
    }
