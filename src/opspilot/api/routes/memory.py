"""Memory and Consultation over HTTP (ADR-0031, ADR-0032, ADR-0035).

Two rules run through every route here and are the reason they are not generic
CRUD.

**The actor is never taken from the request.** It comes from the caller's
resolved **Identity** — the same rule as an Asset event, a Resolution and a
Correction. These are decisions about what the assistant will believe, so the one
thing that must not be self-reported is who decided.

**A Consultation is visible to its author and to admins.** Not a convenience:
ADR-0032 buys "cheap and deletable" with privacy, and a surface colleagues can
browse is one where people weigh their words.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ...auth import Identity, require_role
from ...memory import RESOLUTIONS, AdmissionError

router = APIRouter()

_viewer = Depends(require_role("viewer"))
# Admitting an entry, superseding one, pinning, opening a working set — all acts.
_operator = Depends(require_role("operator"))


# ── Memory ────────────────────────────────────────────────────────────


class AdmitRequest(BaseModel):
    statement: str
    reason: str
    scope: str | None = None
    asset_id: str | None = None
    review_after: str | None = None


class SupersedeRequest(BaseModel):
    statement: str
    reason: str
    review_after: str | None = None


def _memory(request: Request) -> Any:
    store = getattr(request.app.state, "memory", None)
    if store is None:
        raise HTTPException(status_code=503, detail="memory store unavailable")
    return store


@router.get("/memory")
async def list_memory(
    request: Request,
    scope: str | None = Query(None),
    asset_id: str | None = Query(None),
    include_retired: bool = Query(False),
    identity: Identity = _viewer,
) -> dict[str, Any]:
    """List Memory entries; with an anchor, only what applies there.

    Anchored reads are a **filter, not a ranking** — Memory never joins hybrid
    search, so there is no relevance order to ask for.
    """
    store = _memory(request)
    anchored = bool(scope or asset_id)
    if anchored:
        entries = store.applicable(asset_id=asset_id, scope=scope)
    else:
        entries = store.list_entries(include_retired=include_retired)
    return {
        "entries": [_entry(e) for e in entries],
        "total": len(entries),
        # An anchored read is "what applies here", which retired entries by
        # definition do not. Say so rather than dropping the flag in silence —
        # a filter that quietly ignores half its input is the same failure this
        # domain keeps arguing against.
        "include_retired_ignored": anchored and include_retired,
    }


@router.get("/memory/scopes")
async def list_scopes(request: Request, identity: Identity = _viewer) -> dict[str, Any]:
    """The scopes already in use — the pick side of pick-or-create."""
    return {"scopes": _memory(request).scopes()}


@router.post("/memory")
async def admit_memory(
    body: AdmitRequest, request: Request, identity: Identity = _operator
) -> dict[str, Any]:
    """Admit one entry. The reason is mandatory and the actor is the caller."""
    try:
        entry = _memory(request).admit(
            statement=body.statement,
            reason=body.reason,
            actor=identity.name,
            scope=body.scope,
            asset_id=body.asset_id,
            review_after=body.review_after,
        )
    except AdmissionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _entry(entry)


@router.post("/memory/{entry_id}/supersede")
async def supersede_memory(
    entry_id: str, body: SupersedeRequest, request: Request, identity: Identity = _operator
) -> dict[str, Any]:
    """Append a replacement; the old entry is kept and marked superseded."""
    try:
        entry = _memory(request).supersede(
            entry_id,
            statement=body.statement,
            reason=body.reason,
            actor=identity.name,
            review_after=body.review_after,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AdmissionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _entry(entry)


@router.post("/memory/{entry_id}/archive")
async def archive_memory(
    entry_id: str, request: Request, identity: Identity = _operator
) -> dict[str, Any]:
    """Retire an entry that simply no longer holds, without replacing it."""
    try:
        _memory(request).archive(entry_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"id": entry_id, "archived": True}


# ── Memory ↔ KB conflicts ─────────────────────────────────────────────


class ResolveConflictRequest(BaseModel):
    resolution: str
    note: str = ""


def _conflicts(request: Request) -> Any:
    store = getattr(request.app.state, "memory_conflicts", None)
    if store is None:
        raise HTTPException(status_code=503, detail="conflict store unavailable")
    return store


@router.get("/memory/conflicts")
async def list_memory_conflicts(
    request: Request, status: str = Query("open"), identity: Identity = _viewer
) -> dict[str, Any]:
    """Disagreements between a recorded constraint and an ingested document."""
    rows = _conflicts(request).list_conflicts(status=status or None)
    return {"conflicts": [_conflict(c) for c in rows], "total": len(rows)}


@router.patch("/memory/conflicts/{conflict_id}/resolve")
async def resolve_memory_conflict(
    conflict_id: str,
    body: ResolveConflictRequest,
    request: Request,
    identity: Identity = _operator,
) -> dict[str, Any]:
    """Settle one. Detecting was automatic; deciding which side loses is not.

    ``merged`` is deliberately not offered: merging would mean editing a Memory
    entry in place, and an entry is superseded by appending.
    """
    if body.resolution not in RESOLUTIONS:
        raise HTTPException(status_code=400, detail=f"resolution must be one of {RESOLUTIONS}")
    try:
        _conflicts(request).resolve(
            conflict_id, resolution=body.resolution, resolved_by=identity.name, note=body.note
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"id": conflict_id, "status": body.resolution}


# ── Consultations ─────────────────────────────────────────────────────


class PinRequest(BaseModel):
    reason: str
    statement: str | None = None
    scope: str | None = None
    asset_id: str | None = None
    review_after: str | None = None


def _consultations(request: Request) -> Any:
    store = getattr(request.app.state, "consultations", None)
    if store is None:
        raise HTTPException(status_code=503, detail="consultation store unavailable")
    return store


def _visible(store: Any, consultation_id: str, identity: Identity) -> Any:
    con = store.get(consultation_id)
    if con is None:
        raise HTTPException(status_code=404, detail="consultation not found")
    if not con.visible_to(name=identity.name, role=identity.role):
        # 404 rather than 403: whether someone else's conversation exists is
        # itself private.
        raise HTTPException(status_code=404, detail="consultation not found")
    return con


@router.get("/consultations")
async def list_consultations(
    request: Request, limit: int = Query(50, ge=1, le=200), identity: Identity = _viewer
) -> dict[str, Any]:
    """Your Consultations — or everyone's, for an admin."""
    rows = _consultations(request).list_for(name=identity.name, role=identity.role, limit=limit)
    return {"consultations": [_con(c) for c in rows], "total": len(rows)}


@router.get("/consultations/{consultation_id}")
async def get_consultation(
    consultation_id: str, request: Request, identity: Identity = _viewer
) -> dict[str, Any]:
    store = _consultations(request)
    con = _visible(store, consultation_id, identity)
    return {
        **_con(con),
        "messages": [
            {"id": m.id, "seq": m.seq, "role": m.role, "content": m.content, "at": m.created_at}
            for m in store.messages(consultation_id)
        ],
    }


@router.post("/consultations/{consultation_id}/messages/{message_id}/pin")
async def pin_message(
    consultation_id: str,
    message_id: str,
    body: PinRequest,
    request: Request,
    identity: Identity = _operator,
) -> dict[str, Any]:
    """Admit this message as a Memory entry, and pin the Consultation it cites.

    If the entry is not admissible — a missing reason, one global constraint too
    many — nothing is pinned either: a refused admission should leave no trace of
    a citation that does not exist.
    """
    from ...consultation import pin_to_memory

    store = _consultations(request)
    _visible(store, consultation_id, identity)
    try:
        entry = pin_to_memory(
            store,
            _memory(request),
            message_id=message_id,
            # Bind the message to the Consultation the caller was cleared for.
            consultation_id=consultation_id,
            reason=body.reason,
            actor=identity.name,
            statement=body.statement,
            scope=body.scope,
            asset_id=body.asset_id,
            review_after=body.review_after,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AdmissionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _entry(entry)


class EscalateRequest(BaseModel):
    description: str


@router.post("/consultations/{consultation_id}/escalate")
async def escalate_consultation(
    consultation_id: str,
    body: EscalateRequest,
    request: Request,
    identity: Identity = _operator,
) -> dict[str, Any]:
    """Run a Session from this conversation's conclusion.

    Only the Work item description travels — not the transcript. A **Fixture** is
    a frozen input package and a Session's replayability rests on its input
    having edges; an arbitrarily long conversation, small talk and dead ends
    included, is not freezable, and the harness is the gate a Stage is declared
    complete against.

    The Consultation is pinned in the same act: the Session's trace is permanent,
    and its back-reference must not point at something the sweep deleted.
    """
    import asyncio

    from ...consultation import EscalationError, escalate

    state = request.app.state
    store = _consultations(request)
    _visible(store, consultation_id, identity)
    loop = asyncio.get_event_loop()

    def _run() -> Any:
        return escalate(
            store,
            consultation_id,
            description=body.description,
            actor=identity.name,
            session_manager=state.session_mgr,
            playbook=state.playbook,
            provider=state.chat_provider,
            redactor=state.redactor,
            embed_fn=state.embed_fn,
            sqlite_store=state.sqlite,
            lance_store=state.lance,
            mcp_registry=getattr(state, "mcp_registry", None),
        )

    try:
        result = await loop.run_in_executor(None, _run)
    except EscalationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "consultation_id": consultation_id,
        "session_id": result.session_id,
        "artifact_id": result.artifact_id,
        "schema_valid": result.schema_valid,
        "escalated_by": identity.name,
    }


# ── Working set ───────────────────────────────────────────────────────


class OpenWorkingSetRequest(BaseModel):
    title: str
    scope: str | None = None
    asset_id: str | None = None


def _working_sets(request: Request) -> Any:
    store = getattr(request.app.state, "working_sets", None)
    if store is None:
        raise HTTPException(status_code=503, detail="working set store unavailable")
    return store


@router.get("/working-set")
async def get_working_set(request: Request, identity: Identity = _viewer) -> dict[str, Any]:
    """Your open Working set, and any inactivity closure not yet announced."""
    store = _working_sets(request)
    notice = store.take_announcement(identity.name)
    current = store.current(identity.name)
    return {"working_set": _ws(current) if current else None, "notice": notice}


@router.post("/working-set")
async def open_working_set(
    body: OpenWorkingSetRequest, request: Request, identity: Identity = _operator
) -> dict[str, Any]:
    """Start chasing a problem. Any set already open is closed as a deliberate switch."""
    try:
        ws = _working_sets(request).open(
            owner=identity.name, title=body.title, scope=body.scope, asset_id=body.asset_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _ws(ws)


@router.delete("/working-set")
async def close_working_set(request: Request, identity: Identity = _operator) -> dict[str, Any]:
    """Close the open Working set — the problem is done."""
    store = _working_sets(request)
    current = store.current(identity.name)
    if current is None:
        raise HTTPException(status_code=404, detail="no working set open")
    store.close(current.id)
    return {"id": current.id, "closed": True}


# ── serialisation ─────────────────────────────────────────────────────


def _entry(e: Any) -> dict[str, Any]:
    return {
        "id": e.id,
        "statement": e.statement,
        "reason": e.reason,
        "actor": e.actor,
        "created_at": e.created_at,
        "review_after": e.review_after,
        "scope": e.scope,
        "asset_id": e.asset_id,
        "source_ref": e.source_ref,
        "superseded_by": e.superseded_by,
        "archived_at": e.archived_at,
        "is_live": e.is_live,
    }


def _conflict(c: Any) -> dict[str, Any]:
    return {
        "id": c.id,
        "memory_id": c.memory_id,
        "chunk_id": c.chunk_id,
        "note": c.note,
        "detected_in": c.detected_in,
        "detected_at": c.detected_at,
        "status": c.status,
        "resolved_by": c.resolved_by,
        "resolution_note": c.resolution_note,
    }


def _con(c: Any) -> dict[str, Any]:
    return {
        "id": c.id,
        "author": c.author,
        "title": c.title,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "pinned_reason": c.pinned_reason,
        "session_id": c.session_id,
    }


def _ws(w: Any) -> dict[str, Any]:
    return {
        "id": w.id,
        "title": w.title,
        "scope": w.scope,
        "asset_id": w.asset_id,
        "opened_at": w.opened_at,
        "last_active_at": w.last_active_at,
    }
