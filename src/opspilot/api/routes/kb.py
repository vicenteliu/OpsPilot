"""KB API routes: GET /api/kb/docs, POST /api/kb/ingest, GET /api/kb/search,
GET /api/kb/conflicts, PATCH /api/kb/conflicts/{id}/resolve,
POST /api/kb/chunks/{id}/correct, GET /api/kb/corrections."""

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
                "valid_from": h.valid_from,
                "has_open_conflicts": h.has_open_conflicts,
                "content": (h.content or "")[:500],
            }
            for h in hits
        ],
    }


@router.get("/kb/conflicts")
async def list_conflicts(
    request: Request,
    status: str = Query("open", description="Filter status (open/all)"),
    limit: int = Query(50, description="Max rows"),
) -> dict[str, Any]:
    """List KB conflict records."""
    state = request.app.state
    loop = asyncio.get_event_loop()

    def _run() -> Any:
        return state.sqlite.list_conflicts(
            status=None if status == "all" else status,
            limit=limit,
        )

    rows = await loop.run_in_executor(None, _run)
    return {"conflicts": rows, "total": len(rows)}


class ResolveRequest(BaseModel):
    resolution: str  # a_wins | b_wins | merged | dismissed
    resolved_by: str = "api-user"
    note: str = ""


@router.patch("/kb/conflicts/{conflict_id}/resolve")
async def resolve_conflict_route(
    conflict_id: str, body: ResolveRequest, request: Request
) -> dict[str, Any]:
    """Apply a resolution to an open KB conflict."""
    state = request.app.state

    from ...memory.conflict import resolve_conflict

    loop = asyncio.get_event_loop()

    def _run() -> None:
        resolve_conflict(
            conflict_id,
            resolution=body.resolution,
            resolved_by=body.resolved_by,
            note=body.note,
            sqlite=state.sqlite,
        )

    try:
        await loop.run_in_executor(None, _run)
    except (ValueError, KeyError) as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {"conflict_id": conflict_id, "resolution": body.resolution, "ok": True}


# ── Corrections ──────────────────────────────────────────────────────────────


class CorrectRequest(BaseModel):
    new_content: str
    reason: str
    corrected_by: str = "api-user"


@router.post("/kb/chunks/{chunk_id}/correct")
async def correct_chunk(
    chunk_id: str, body: CorrectRequest, request: Request
) -> dict[str, Any]:
    """Apply an inline content correction to a KB chunk."""
    state = request.app.state
    loop = asyncio.get_event_loop()

    def _run() -> str:
        return state.sqlite.add_correction(
            chunk_id,
            corrected_by=body.corrected_by,
            reason=body.reason,
            new_content=body.new_content,
        )

    try:
        corr_id = await loop.run_in_executor(None, _run)
    except KeyError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {"corr_id": corr_id, "chunk_id": chunk_id, "ok": True}


@router.get("/kb/corrections")
async def list_corrections_route(
    request: Request,
    chunk_id: str | None = Query(None, description="Filter to a specific chunk"),
    limit: int = Query(50, description="Max rows"),
) -> dict[str, Any]:
    """List KB correction records, newest first."""
    state = request.app.state
    loop = asyncio.get_event_loop()

    def _run() -> list[dict[str, Any]]:
        return state.sqlite.list_corrections(chunk_id=chunk_id, limit=limit)

    rows = await loop.run_in_executor(None, _run)
    return {"corrections": rows, "total": len(rows)}
