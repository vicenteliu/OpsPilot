"""FastAPI application for OpsPilot.

Exposes:
  GET  /api/config  — returns active model ref and enabled UI modules
  POST /api/run     — runs the ticket summary playbook on a submitted ticket
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import load_config
from ..memory.lance_store import LanceStore
from ..memory.sqlite_store import SqliteStore
from ..memory.storage_init import init_sqlite
from ..orchestrator.types import load_playbook
from ..providers.registry import make_provider
from ..redaction import Redactor
from ..session.manager import SessionManager
from .routes.config import router as config_router
from .routes.run import router as run_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise all heavy resources on startup; clean up on shutdown."""
    cfg = load_config()

    playbooks_base = cfg.playbooks_dir or Path("playbooks")
    playbook_id = os.environ.get("OPSPILOT_DEFAULT_PLAYBOOK", "pb_ticket_summary_zh")
    playbook = load_playbook(playbooks_base / playbook_id)

    # Build the active_model_ref string returned by /api/config.
    active_model_ref = (
        f"{playbook.model.provider_id}/{playbook.model.name}@{playbook.model.version}"
    )

    # Ensure KB directory exists.
    kb_dir = cfg.home / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)

    # SQLite store — init schema on first run; open without re-running afterwards.
    sqlite_db_path = kb_dir / "sqlite.db"
    conn = init_sqlite(sqlite_db_path)
    sqlite = SqliteStore(conn)

    lance = LanceStore.open_or_create(
        kb_dir / "lancedb",
        dim=768,
        embedding_model=cfg.embed_model,
    )

    # Chat provider is determined by the playbook's model config.
    chat_provider = make_provider(
        playbook.model.provider_id,
        kind=playbook.model.kind,
        api_key=cfg.anthropic_api_key,
    )

    # Embed provider is always Ollama (Anthropic does not support embeddings).
    embed_provider = make_provider("ollama-local", base_url=cfg.ollama_base_url)

    def embed_fn(text: str) -> list[float]:
        return embed_provider.embed([text], model=cfg.embed_model)[0]

    session_mgr = SessionManager(home=cfg.home)
    redactor = Redactor.from_yaml()

    app.state.cfg = cfg
    app.state.playbook = playbook
    app.state.active_model_ref = active_model_ref
    app.state.sqlite = sqlite
    app.state.lance = lance
    app.state.chat_provider = chat_provider
    app.state.embed_fn = embed_fn
    app.state.session_mgr = session_mgr
    app.state.redactor = redactor

    yield
    # No teardown required; SQLite connections and Ollama HTTP clients
    # are closed by the OS on process exit for this single-user deployment.


app = FastAPI(title="OpsPilot API", version="0.2.0", lifespan=lifespan)

# Allow Svelte dev server (5173) and preview server (4173) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router, prefix="/api")
app.include_router(run_router, prefix="/api")
