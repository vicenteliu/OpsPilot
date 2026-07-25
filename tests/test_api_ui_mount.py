"""All-in-one UI static mount (ADR-0020, #100).

FastAPI serves the pre-built SvelteKit UI, but /api, /health and /metrics
must always win over the catch-all static mount.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.app import _mount_ui


def _app_with_ui(ui_dir: Path) -> FastAPI:
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"pong": "yes"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    with patch.dict(os.environ, {"OPSPILOT_UI_DIR": str(ui_dir)}, clear=False):
        _mount_ui(app)
    return app


class TestUiMount:
    def test_serves_index_and_does_not_shadow_api(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text("<html>OpsPilot UI</html>", encoding="utf-8")
        (tmp_path / "app.css").write_text("body{}", encoding="utf-8")
        client = TestClient(_app_with_ui(tmp_path))
        # Root serves the SPA shell.
        root = client.get("/")
        assert root.status_code == 200
        assert "OpsPilot UI" in root.text
        # A static asset is served.
        assert client.get("/app.css").status_code == 200
        # API and ops routes still win over the "/" mount.
        assert client.get("/api/ping").json() == {"pong": "yes"}
        assert client.get("/health").json() == {"status": "ok"}

    def test_no_mount_when_ui_dir_absent(self, tmp_path: Path) -> None:
        # Point at an empty dir (no index.html) → mount skipped, no crash.
        app = FastAPI()

        @app.get("/api/ping")
        def ping() -> dict[str, str]:
            return {"pong": "yes"}

        with patch.dict(os.environ, {"OPSPILOT_UI_DIR": str(tmp_path)}, clear=False):
            _mount_ui(app)
        client = TestClient(app)
        assert client.get("/api/ping").status_code == 200
        assert client.get("/").status_code == 404  # nothing mounted at root
