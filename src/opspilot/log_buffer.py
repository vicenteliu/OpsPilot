"""In-memory ring buffer of recent log records for the admin log viewer.

A logging handler keeps the last N records so the admin module can show
recent system logs without shipping them anywhere. It complements — never
replaces — stdout/JSON logging (that remains the source of truth for real
log aggregation). Bounded and ephemeral: records are lost on restart, and
with multiple uvicorn workers each process keeps its own buffer.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from typing import Any

from .observability import request_id_var
from .timeutil import UTC

MAX_RECORDS = 1000
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class RingBufferHandler(logging.Handler):
    """Keep the most recent log records as plain dicts (newest last)."""

    def __init__(self, capacity: int = MAX_RECORDS) -> None:
        super().__init__()
        self._buf: deque[dict[str, Any]] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = (
                datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
                + "Z"
            )
            self._buf.append(
                {
                    "ts": ts,
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                    "request_id": getattr(record, "request_id", None) or request_id_var.get(),
                }
            )
        except Exception:  # noqa: BLE001 — a logging handler must never raise
            self.handleError(record)

    def records(self, *, level: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Return up to *limit* most-recent records, optionally at/above *level*."""
        items = list(self._buf)
        if level and level in _LEVELS:
            threshold = _LEVELS.index(level)
            items = [r for r in items if _rank(r["level"]) >= threshold]
        return items[-limit:]


def _rank(level_name: str) -> int:
    try:
        return _LEVELS.index(level_name)
    except ValueError:
        return 0


_HANDLER: RingBufferHandler | None = None


def install(level: int = logging.INFO) -> RingBufferHandler:
    """Attach the ring buffer to the root logger once; idempotent.

    Call after any ``configure_json_logging`` (which clears root handlers) so
    the buffer isn't removed. Lowers the root level to *level* if it was
    higher, so INFO access logs are actually captured.
    """
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = RingBufferHandler()
        _HANDLER.setLevel(level)
        root = logging.getLogger()
        root.addHandler(_HANDLER)
        if root.level == logging.NOTSET or root.level > level:
            root.setLevel(level)
    return _HANDLER


def get_handler() -> RingBufferHandler | None:
    return _HANDLER
