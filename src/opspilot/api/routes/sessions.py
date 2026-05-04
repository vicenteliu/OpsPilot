"""GET /api/sessions and GET /api/sessions/{session_id} routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from ..types import ApiRunResponse, ApiSessionListResponse, ApiSessionSummary

router = APIRouter()

_MAX_SESSIONS = 50


@router.get("/sessions", response_model=ApiSessionListResponse)
def list_sessions(request: Request) -> ApiSessionListResponse:
    """Return the most recent sessions (newest first)."""
    mgr = request.app.state.session_mgr
    session_ids = mgr.list()

    rows: list[ApiSessionSummary] = []
    for sid in reversed(session_ids[-_MAX_SESSIONS:]):
        try:
            sess = mgr.load(sid)
            art_ids = mgr.artifacts(sid).list_ids()
            artifact_id = art_ids[0] if art_ids else None
            rows.append(
                ApiSessionSummary(
                    session_id=sid,
                    created_at=sess.created_at,
                    status=sess.status.value if hasattr(sess.status, "value") else str(sess.status),
                    artifact_id=artifact_id,
                )
            )
        except Exception:  # noqa: BLE001
            continue

    return ApiSessionListResponse(sessions=rows)


@router.get("/sessions/{session_id}", response_model=ApiRunResponse)
def get_session(session_id: str, request: Request) -> ApiRunResponse:
    """Return the full result for a past session."""
    mgr = request.app.state.session_mgr
    try:
        sess = mgr.load(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found") from exc

    art_store = mgr.artifacts(session_id)
    art_ids = art_store.list_ids()
    if not art_ids:
        return ApiRunResponse(
            session_id=session_id,
            artifact_id=None,
            schema_valid=sess.status.value == "archived"
            if hasattr(sess.status, "value")
            else sess.status == "archived",
            result={},
            error="No artifact found for this session",
        )

    artifact_id = art_ids[0]
    try:
        content = art_store.read_text(artifact_id)
        summary = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read artifact: {e}") from e

    status = sess.status.value if hasattr(sess.status, "value") else str(sess.status)
    return ApiRunResponse(
        session_id=session_id,
        artifact_id=artifact_id,
        schema_valid=status == "archived",
        result=summary,
        error=None,
    )
