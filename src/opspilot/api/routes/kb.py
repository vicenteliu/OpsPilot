"""KB API routes: GET /api/kb/docs, GET /api/kb/stats, POST /api/kb/ingest,
GET /api/kb/search, GET /api/kb/conflicts, PATCH /api/kb/conflicts/{id}/resolve,
POST /api/kb/chunks/{id}/correct, GET /api/kb/corrections.

Conflict resolutions and chunk corrections record who acted, taken from the
caller's resolved **Identity** rather than from the request body — an
attribution the caller chooses is not evidence of who acted.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ...auth import Identity, require_role
from ...kb.ingestion import SourceAuthority

router = APIRouter()

# Overriding a chunk or settling a conflict is an act, not a read: the glossary
# puts KB *search* under viewer and acting under operator (ADR-0020).
_operator = Depends(require_role("operator"))
_viewer = Depends(require_role("viewer"))


@router.get("/kb/stats")
async def kb_stats(request: Request) -> dict[str, Any]:
    """Return aggregate KB health counts (docs, chunks, open conflicts, corrections)."""
    state = request.app.state
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, state.sqlite.kb_stats)


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
    # Provenance recorded on every document in this batch. Validated here so a
    # bad value is a 422 naming the four choices, not a sqlite CHECK failure
    # after half the batch has been written.
    source_authority: SourceAuthority = "internal"


@router.post("/kb/ingest")
async def ingest_docs(body: IngestRequest, request: Request) -> dict[str, Any]:
    """Ingest one or more files into the KB."""
    state = request.app.state

    from ...kb.ingestion import IngestConfig
    from ...kb.ingestion import ingest as run_ingest

    paths = [Path(p) for p in body.paths]
    ic = IngestConfig(
        kb_id=body.kb_id,
        namespace=body.namespace,
        classification=body.classification,
        # Stamp records with the vector table's own declared model so the
        # LanceStore accepts them. Fabricating a different string here (e.g.
        # a fully-qualified ref while the table was opened with the bare
        # model name) makes upsert_vectors reject every record — the FTS
        # write still commits, leaving keyword-only chunks with no vectors.
        embedding_model=state.lance.embedding_model,
        embedding_dim=state.lance.dim,
        source_authority=body.source_authority,
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

    from ...kb.retrieval import kb_search

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
                "has_correction": h.has_correction,
                # Provenance of the citation. Retrieval has always resolved it
                # onto the Hit; it just never reached the caller, which is why
                # no interface could show what an answer rested on.
                "source_authority": h.source_authority,
                "content": (h.content or "")[:500],
            }
            for h in hits
        ],
    }


class DeleteDocRequest(BaseModel):
    reason: str


@router.delete("/kb/docs/{document_id}")
async def delete_doc(
    document_id: str,
    body: DeleteDocRequest,
    request: Request,
    identity: Identity = _operator,
) -> dict[str, Any]:
    """Remove a document, its chunks, its vectors, and the decisions quoting it.

    A **hard** delete. The case this answers is "we ingested something we should
    not have" — a wrong folder, a directory with secrets — and a soft delete
    leaves the content in the database, which does not answer it.

    Operator, because removing knowledge is at least as much an act as
    correcting it, and the actor comes from the caller's Identity rather than
    the body — the rule already established for Resolutions and Corrections.

    What survives is a record of the removal: what went, who decided, and why,
    quoting nothing.
    """
    state = request.app.state
    loop = asyncio.get_event_loop()

    def _run() -> Any:
        report = state.sqlite.delete_document(document_id, actor=identity.name, reason=body.reason)
        # SQLite cascades the chunks and the FTS trigger keeps keyword search in
        # step; the vectors are this caller's job.
        if report["vector_ids"] and getattr(state, "lance", None) is not None:
            state.lance.delete_by_vector_ids(report["vector_ids"])
        return report

    try:
        report = await loop.run_in_executor(None, _run)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "id": report["id"],
        "document_id": document_id,
        "chunks_removed": report["chunks_removed"],
        "vectors_removed": len(report["vector_ids"]),
        "corrections_removed": report["corrections_removed"],
        "conflicts_removed": report["conflicts_removed"],
        "deleted_by": report["actor"],
    }


@router.get("/kb/deletions")
async def list_deletions_route(
    request: Request, limit: int = Query(50, ge=1, le=200), identity: Identity = _viewer
) -> dict[str, Any]:
    """What has been removed, by whom and why. Never the content."""
    loop = asyncio.get_event_loop()
    rows = await loop.run_in_executor(
        None, lambda: request.app.state.sqlite.list_deletions(limit=limit)
    )
    return {"deletions": rows, "total": len(rows)}


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
    note: str = ""


@router.patch("/kb/conflicts/{conflict_id}/resolve")
async def resolve_conflict_route(
    conflict_id: str, body: ResolveRequest, request: Request, identity: Identity = _operator
) -> dict[str, Any]:
    """Apply a resolution to an open KB conflict."""
    state = request.app.state

    from ...kb.conflict import resolve_conflict

    loop = asyncio.get_event_loop()

    def _run() -> None:
        resolve_conflict(
            conflict_id,
            resolution=body.resolution,
            resolved_by=identity.name,
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


@router.post("/kb/chunks/{chunk_id}/correct")
async def correct_chunk(
    chunk_id: str, body: CorrectRequest, request: Request, identity: Identity = _operator
) -> dict[str, Any]:
    """Apply an inline content correction to a KB chunk."""
    state = request.app.state
    loop = asyncio.get_event_loop()

    def _run() -> str:
        return cast(
            "str",
            state.sqlite.add_correction(
                chunk_id,
                corrected_by=identity.name,
                reason=body.reason,
                new_content=body.new_content,
            ),
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
        return cast(
            "list[dict[str, Any]]", state.sqlite.list_corrections(chunk_id=chunk_id, limit=limit)
        )

    rows = await loop.run_in_executor(None, _run)
    return {"corrections": rows, "total": len(rows)}
