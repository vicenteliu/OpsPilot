"""Tests for /health and /metrics endpoints (PR-32)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.middleware import ObservabilityMiddleware, metrics_text
from opspilot.api.routes.health import router as health_router
from opspilot.api.routes.metrics import router as metrics_router


def _make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.cfg = SimpleNamespace(home=tmp_path)
    app.add_middleware(ObservabilityMiddleware)
    app.include_router(health_router)
    app.include_router(metrics_router)
    return app


# ── /health ───────────────────────────────────────────────────────────────


def test_health_returns_ok(tmp_path: Path):
    with TestClient(_make_app(tmp_path)) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_health_has_version(tmp_path: Path):
    with TestClient(_make_app(tmp_path)) as client:
        resp = client.get("/health")
    data = resp.json()
    assert "version" in data
    assert data["version"]  # non-empty


def test_health_has_uptime(tmp_path: Path):
    with TestClient(_make_app(tmp_path)) as client:
        resp = client.get("/health")
    data = resp.json()
    assert "uptime_seconds" in data
    assert isinstance(data["uptime_seconds"], int)


def test_health_has_home(tmp_path: Path):
    with TestClient(_make_app(tmp_path)) as client:
        resp = client.get("/health")
    data = resp.json()
    assert str(tmp_path) in data["home"]


# ── /metrics ──────────────────────────────────────────────────────────────


def test_metrics_returns_text(tmp_path: Path):
    with TestClient(_make_app(tmp_path)) as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


def test_metrics_increments_after_request(tmp_path: Path):
    with TestClient(_make_app(tmp_path)) as client:
        client.get("/health")
        resp = client.get("/metrics")
    body = resp.text
    # Should contain a counter line for the /health request
    assert "opspilot_http_requests_total" in body


def test_metrics_format_has_type_comment(tmp_path: Path):
    with TestClient(_make_app(tmp_path)) as client:
        client.get("/health")
        resp = client.get("/metrics")
    assert "# TYPE" in resp.text


# ── metrics_text() unit ───────────────────────────────────────────────────


def test_metrics_text_counter():
    from opspilot.api.middleware import inc
    inc("test_counter_xyz", {"label": "val"})
    text = metrics_text()
    assert "test_counter_xyz" in text
    assert 'label="val"' in text


def test_metrics_text_histogram():
    from opspilot.api.middleware import observe
    observe("test_histogram_xyz", 0.123)
    text = metrics_text()
    assert "test_histogram_xyz_seconds_count" in text
    assert "test_histogram_xyz_seconds_sum" in text


# ── JSON logging ──────────────────────────────────────────────────────────


def test_json_formatter_produces_valid_json():
    import json
    import logging
    from opspilot.api.middleware import JsonFormatter

    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello %s", args=("world",), exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["msg"] == "hello world"
    assert data["severity"] == "INFO"
    assert "ts" in data
