"""KB corrections and conflict resolutions record the caller, not the client.

Both endpoints once took ``corrected_by`` / ``resolved_by`` from the request
body, and every client shipped its own constant (``web-user``, ``cli-user``,
``tui-user``, ``api-user``), so the stored value said which client was used
rather than who used it. These lock in the identity-derived attribution and
the operator gate that comes with it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.kb import router as kb_router
from opspilot.auth import AuthStore
from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite

EMBED_MODEL = "nomic-embed-text-v2-moe"


def _client(tmp_path: Path, *, service_token: str | None = None) -> tuple[TestClient, SqliteStore]:
    app = FastAPI()
    app.include_router(kb_router, prefix="/api")
    conn = init_sqlite(tmp_path / "kb.db")
    sqlite = SqliteStore(conn)
    app.state.sqlite = sqlite
    # No users + no service token → the deps fall back to a local-dev operator.
    app.state.auth = AuthStore(conn)
    app.state.service_token = service_token
    return TestClient(app), sqlite


DOC_ID = "doc_1111aaaa"


def _doc(sqlite: SqliteStore) -> None:
    """Create the parent document once.

    upsert_document is INSERT OR REPLACE and kb_chunks cascades on delete, so
    calling this again after chunks exist would wipe them.
    """
    sqlite.upsert_document(
        {
            "id": DOC_ID,
            "source_path": f"/{DOC_ID}.md",
            "title": "VPN runbook",
            "classification": "internal",
            "content_hash": "sha256:" + ("a" * 64),
            "ingested_at": "2026-01-01T00:00:00Z",
            "language": "en",
            "tags": [],
            "namespace": "ns",
            "chunk_strategy": "headings_then_size",
            "chunk_count": 1,
            "embedding_model": EMBED_MODEL,
            "embedding_dim": 768,
            "redaction_passed": True,
            "valid_from": None,
        }
    )


def _chunk(sqlite: SqliteStore, chunk_id: str = "chk_aaaa1111", seq: int = 0) -> str:
    content = "VPN gateway is vpn-a.corp.example"
    row: dict[str, Any] = {
        "id": chunk_id,
        "document_id": DOC_ID,
        "seq": seq,
        "content": content,
        "content_hash": "sha256:" + ("b" * 64),
        "char_start": 0,
        "char_end": len(content),
        "line_start": 1,
        "line_end": 1,
        "embedding_model": EMBED_MODEL,
        "vector_id": f"vec_{chunk_id}",
        "metadata": {"namespace": "ns", "classification": "internal", "language": "en", "tags": []},
    }
    sqlite.upsert_chunks([row])
    return chunk_id


class TestCorrectionAttribution:
    def test_records_identity_not_the_body(self, tmp_path: Path) -> None:
        client, sqlite = _client(tmp_path)
        _doc(sqlite)
        chunk_id = _chunk(sqlite)
        res = client.post(
            f"/api/kb/chunks/{chunk_id}/correct",
            # A forged attribution: ignored, because the models do not set
            # extra, so this is dropped rather than rejected.
            json={
                "new_content": "vpn-b.corp.example",
                "reason": "gateway moved",
                "corrected_by": "someone-else",
            },
        )
        assert res.status_code == 200
        rows = sqlite.list_corrections()
        assert len(rows) == 1
        assert rows[0]["corrected_by"] == "local-dev"

    def test_service_token_identity_is_recorded(self, tmp_path: Path) -> None:
        client, sqlite = _client(tmp_path, service_token="tok-abcdef-secret")
        _doc(sqlite)
        chunk_id = _chunk(sqlite)
        res = client.post(
            f"/api/kb/chunks/{chunk_id}/correct",
            json={"new_content": "vpn-b.corp.example", "reason": "gateway moved"},
            headers={"Authorization": "Bearer tok-abcdef-secret"},
        )
        assert res.status_code == 200
        assert sqlite.list_corrections()[0]["corrected_by"] == "svc:tok-ab"


class TestConflictAttribution:
    def test_resolution_records_identity(self, tmp_path: Path) -> None:
        client, sqlite = _client(tmp_path)
        _doc(sqlite)
        chunk_a = _chunk(sqlite, "chk_aaaa1111")
        chunk_b = _chunk(sqlite, "chk_bbbb2222", seq=1)  # (document_id, seq) is unique
        conflict_id = "conf_abcd1234"
        sqlite.upsert_conflict(
            {
                "id": conflict_id,
                "chunk_a_id": chunk_a,
                "chunk_b_id": chunk_b,
                "doc_a_id": DOC_ID,
                "doc_b_id": DOC_ID,
                "conflict_type": "direct_contradiction",
                "similarity": 0.91,
                "status": "open",
                "detected_at": "2026-07-26T00:00:00Z",
            }
        )
        res = client.patch(
            f"/api/kb/conflicts/{conflict_id}/resolve",
            json={"resolution": "a_wins", "note": "confirmed with network", "resolved_by": "ceo"},
        )
        assert res.status_code == 200
        row = sqlite.get_conflict(conflict_id)
        assert row is not None
        assert row["resolved_by"] == "local-dev"
        assert row["resolution_note"] == "confirmed with network"  # note stays the caller's


class TestWriteGate:
    """Overriding a chunk is an act, not a read — viewer must not reach it."""

    def test_viewer_is_refused(self, tmp_path: Path) -> None:
        app = FastAPI()
        app.include_router(kb_router, prefix="/api")
        conn = init_sqlite(tmp_path / "kb.db")
        sqlite = SqliteStore(conn)
        app.state.sqlite = sqlite
        auth = AuthStore(conn)
        auth.upsert_user("reader", role="viewer", password="pw-reader-long")
        app.state.auth = auth
        app.state.service_token = None
        _doc(sqlite)
        chunk_id = _chunk(sqlite)

        client = TestClient(app)
        token = auth.create_session("reader")
        client.cookies.set("opspilot_session", token)
        res = client.post(
            f"/api/kb/chunks/{chunk_id}/correct",
            json={"new_content": "nope", "reason": "should not land"},
        )
        assert res.status_code == 403
        assert sqlite.list_corrections() == []
