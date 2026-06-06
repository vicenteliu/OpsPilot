"""FastAPI application for OpsPilot.

Exposes:
  GET  /api/config              — active model ref and enabled UI modules
  POST /api/run                 — run ticket summary playbook
  GET  /api/iteration/lineage   — skill lineage history (PR-28)
  GET  /api/kb/docs             — list ingested KB documents
  POST /api/kb/ingest           — ingest files into KB
  GET  /api/kb/search           — hybrid search over KB
  POST /api/wiki/ingest         — generate wiki page from KB doc
  POST /api/wiki/query-to-page  — convert session to wiki page
  GET  /api/wiki/lint           — lint wiki pages
  POST /api/wiki/promote/{slug} — promote wiki page to live
  POST /api/harness/run         — run eval harness on a fixture
  GET  /api/mcp/servers         — list MCP servers
  GET  /api/mcp/probe/{id}      — probe MCP server health
  POST /api/sandbox/dry-run     — preview sandbox action
  POST /api/sandbox/run         — execute sandbox action
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import load_config
from ..mcp import McpRegistry, load_mcp_config
from ..memory.lance_store import LanceStore
from ..memory.sqlite_store import SqliteStore
from ..memory.storage_init import init_sqlite
from ..orchestrator.types import load_playbook
from ..providers.registry import make_provider
from ..redaction import Redactor
from ..session.manager import SessionManager
from .middleware import ObservabilityMiddleware
from .routes.chat import router as chat_router
from .routes.config import router as config_router
from .routes.harness import router as harness_router
from .routes.health import router as health_router
from .routes.iteration import router as iteration_router
from .routes.kb import router as kb_router
from .routes.mcp import router as mcp_router
from .routes.metrics import router as metrics_router
from .routes.models import router as models_router
from .routes.doc import router as doc_router
from .routes.run import router as run_router
from .routes.sandbox import router as sandbox_router
from .routes.sessions import router as sessions_router
from .routes.wiki import router as wiki_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise all heavy resources on startup; clean up on shutdown."""
    cfg = load_config()

    playbooks_base = cfg.playbooks_dir or Path("playbooks")
    playbook_id = os.environ.get("OPSPILOT_DEFAULT_PLAYBOOK", "pb_ticket_summary_zh")
    playbook = load_playbook(playbooks_base / playbook_id)
    vendor_doc_pb = load_playbook(playbooks_base / "pb_vendor_doc_en")
    request_fulfillment_pb = load_playbook(playbooks_base / "pb_request_fulfillment_zh")
    classify_pb = load_playbook(playbooks_base / "pb_classify_work_item_zh")

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
    vendor_doc_provider = make_provider(
        vendor_doc_pb.model.provider_id,
        kind=vendor_doc_pb.model.kind,
        api_key=cfg.anthropic_api_key,
    )

    # Embed provider is always Ollama (Anthropic does not support embeddings).
    embed_provider = make_provider("ollama-local", base_url=cfg.ollama_base_url)

    def embed_fn(text: str) -> list[float]:
        return embed_provider.embed([text], model=cfg.embed_model)[0]

    session_mgr = SessionManager(home=cfg.home)
    redactor = Redactor.from_yaml()

    mcp_registry: McpRegistry | None = None
    mcp_config_path = Path("mcp-config.yaml")
    if mcp_config_path.exists():
        try:
            mcp_cfg = load_mcp_config(mcp_config_path)
            mcp_registry = McpRegistry.from_config(mcp_cfg)
        except Exception:  # noqa: BLE001 — bad config must not prevent startup
            mcp_registry = None

    app.state.cfg = cfg
    app.state.playbook = playbook
    app.state.vendor_doc_pb = vendor_doc_pb
    app.state.request_fulfillment_pb = request_fulfillment_pb
    app.state.classify_pb = classify_pb
    app.state.classify_threshold = float(os.environ.get("OPSPILOT_CLASSIFY_THRESHOLD", "0.7"))
    app.state.vendor_doc_provider = vendor_doc_provider
    app.state.active_model_ref = active_model_ref
    app.state.sqlite = sqlite
    app.state.lance = lance
    app.state.chat_provider = chat_provider
    app.state.embed_fn = embed_fn
    app.state.session_mgr = session_mgr
    app.state.redactor = redactor
    app.state.mcp_registry = mcp_registry

    yield

    if mcp_registry is not None:
        mcp_registry.close_all()


app = FastAPI(title="OpsPilot API", version="0.2.0", lifespan=lifespan)

# Allow Svelte dev server (5173) and preview server (4173) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ObservabilityMiddleware)

app.include_router(health_router)          # /health  (no /api prefix — ops endpoints)
app.include_router(metrics_router)         # /metrics
app.include_router(config_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(run_router, prefix="/api")
app.include_router(doc_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(iteration_router, prefix="/api")
app.include_router(kb_router, prefix="/api")
app.include_router(wiki_router, prefix="/api")
app.include_router(harness_router, prefix="/api")
app.include_router(mcp_router, prefix="/api")
app.include_router(sandbox_router, prefix="/api")
