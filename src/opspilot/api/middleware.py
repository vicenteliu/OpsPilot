"""API middleware: JSON structured logging + in-memory Prometheus-format metrics."""

from __future__ import annotations

import json
import logging
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# ── Structured JSON logging ────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON (OTel-compatible field names)."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"
        entry: dict = {
            "ts": ts,
            "severity": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
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


# ── In-memory Prometheus-format metrics ───────────────────────────────────

_lock = threading.Lock()
# {metric_name: {labels_tuple: value}}
_counters: dict[str, defaultdict[tuple, float]] = defaultdict(lambda: defaultdict(float))
_histograms: dict[str, list[float]] = defaultdict(list)


def inc(metric: str, labels: dict[str, str] | None = None, amount: float = 1.0) -> None:
    key = tuple(sorted((labels or {}).items()))
    with _lock:
        _counters[metric][key] += amount


def observe(metric: str, value: float) -> None:
    with _lock:
        _histograms[metric].append(value)


def metrics_text() -> str:
    """Render counters + histogram summaries as Prometheus text format."""
    lines: list[str] = []
    with _lock:
        for name, label_map in _counters.items():
            lines.append(f"# TYPE {name} counter")
            for labels, val in label_map.items():
                lstr = ",".join(f'{k}="{v}"' for k, v in labels) if labels else ""
                suffix = "{" + lstr + "}" if lstr else ""
                lines.append(f"{name}{suffix} {val:.0f}")

        for name, values in _histograms.items():
            if not values:
                continue
            count = len(values)
            total = sum(values)
            lines.append(f"# TYPE {name}_seconds summary")
            lines.append(f"{name}_seconds_count {count}")
            lines.append(f"{name}_seconds_sum {total:.6f}")
            sorted_v = sorted(values)
            for q, label in ((0.5, "0.5"), (0.9, "0.9"), (0.99, "0.99")):
                idx = min(int(q * count), count - 1)
                lines.append(f'{name}_seconds{{quantile="{label}"}} {sorted_v[idx]:.6f}')

    return "\n".join(lines) + "\n"


# ── Request logging + metrics middleware ───────────────────────────────────


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Log each request as JSON and update Prometheus-format counters."""

    _logger = logging.getLogger("opspilot.api.access")

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start

        path = request.url.path
        method = request.method
        status = str(response.status_code)

        inc("opspilot_http_requests_total", {"path": path, "method": method, "status": status})
        observe("opspilot_http_request_duration", duration)

        self._logger.info(
            "%s %s %s %.3fs",
            method, path, status, duration,
            extra={"path": path, "method": method, "status": status, "duration_s": duration},
        )
        return response
