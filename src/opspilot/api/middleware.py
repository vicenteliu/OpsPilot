"""API middleware: JSON structured logging + Prometheus metrics.

Metrics collectors and the ``request_id`` correlation handle live in
``opspilot.observability`` (dependency-neutral); this module wires them into
the API request lifecycle and the JSON log formatter (ADR-0007).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..observability import HTTP_REQUEST_DURATION, HTTP_REQUESTS, request_id_var

# Contextual extras emitted on a log line when the call site passes them.
_CONTEXT_FIELDS = ("path", "method", "status", "duration_s", "session_id", "playbook")


# ── Structured JSON logging ────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON (OTel-compatible field names).

    Merges the ``request_id`` correlation handle and any contextual ``extra``
    fields the call site passed (``path``, ``status``, ``session_id``, ...).
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = (
            datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            + "Z"
        )
        entry: dict = {
            "ts": ts,
            "severity": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        # Merge contextual extras (only the known fields, to keep logs tidy).
        for key in _CONTEXT_FIELDS:
            val = record.__dict__.get(key)
            if val is not None:
                entry[key] = val
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_json_logging(level: int = logging.INFO) -> None:
    """Replace root handler with JSON formatter.  Call once at startup."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


# ── Request logging + metrics middleware ───────────────────────────────────


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Assign a request_id, log each request as JSON, update HTTP metrics."""

    _logger = logging.getLogger("opspilot.api.access")

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        token = request_id_var.set(uuid.uuid4().hex)
        start = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            duration = time.monotonic() - start

        # Prefer the route template (bounded label cardinality) over the raw URL.
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        method = request.method
        status = str(response.status_code)

        HTTP_REQUESTS.labels(path=path, method=method, status=status).inc()
        HTTP_REQUEST_DURATION.labels(path=path, method=method).observe(duration)

        self._logger.info(
            "%s %s %s %.3fs",
            method,
            path,
            status,
            duration,
            extra={"path": path, "method": method, "status": status, "duration_s": duration},
        )
        request_id_var.reset(token)
        return response
