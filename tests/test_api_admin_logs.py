"""Admin system-log viewer — in-memory ring buffer + admin-only route."""

from __future__ import annotations

import logging
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.admin import router as admin_router
from opspilot.api.routes.auth import router as auth_router
from opspilot.auth import AuthStore
from opspilot.log_buffer import RingBufferHandler


class TestRingBuffer:
    def _rec(self, name: str, level: int, msg: str) -> logging.LogRecord:
        return logging.LogRecord(name, level, __file__, 1, msg, None, None)

    def test_keeps_last_n_newest_last(self) -> None:
        h = RingBufferHandler(capacity=3)
        for i in range(5):
            h.emit(self._rec("opspilot.test", logging.INFO, f"m{i}"))
        msgs = [r["msg"] for r in h.records()]
        assert msgs == ["m2", "m3", "m4"]  # oldest two dropped, newest last

    def test_level_filter_is_at_or_above(self) -> None:
        h = RingBufferHandler()
        h.emit(self._rec("x", logging.INFO, "info"))
        h.emit(self._rec("x", logging.WARNING, "warn"))
        h.emit(self._rec("x", logging.ERROR, "err"))
        assert [r["msg"] for r in h.records(level="WARNING")] == ["warn", "err"]
        assert [r["msg"] for r in h.records(level="ERROR")] == ["err"]
        assert len(h.records()) == 3  # no filter → all

    def test_limit_returns_most_recent(self) -> None:
        h = RingBufferHandler()
        for i in range(10):
            h.emit(self._rec("x", logging.INFO, f"m{i}"))
        assert [r["msg"] for r in h.records(limit=2)] == ["m8", "m9"]

    def test_emit_never_raises_on_bad_record(self) -> None:
        h = RingBufferHandler()
        bad = logging.LogRecord("x", logging.INFO, __file__, 1, "%d", ("not-int",), None)
        h.emit(bad)  # getMessage would raise; handler must swallow


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    store = AuthStore(sqlite3.connect(":memory:", check_same_thread=False))
    app.state.auth = store
    app.state.service_token = None
    store.upsert_user("root", role="admin", password="pw")
    store.upsert_user("olga", role="operator", password="pw")
    return TestClient(app)


class TestLogsRoute:
    def test_admin_gets_records(self) -> None:
        from opspilot import log_buffer

        # Ensure the buffer exists and has a record.
        handler = log_buffer.install()
        logging.getLogger("opspilot.test").warning("admin-log-probe")
        c = _client()
        c.post("/api/auth/login", json={"username": "root", "password": "pw"})
        body = c.get("/api/admin/logs", params={"level": "WARNING"}).json()
        assert body["available"] is True
        assert any("admin-log-probe" in r["msg"] for r in body["records"])
        _ = handler  # keep ref

    def test_operator_forbidden(self) -> None:
        c = _client()
        c.post("/api/auth/login", json={"username": "olga", "password": "pw"})
        assert c.get("/api/admin/logs").status_code == 403

    def test_anonymous_401(self) -> None:
        assert _client().get("/api/admin/logs").status_code == 401
