"""FastAPI application for OpsPilot.

Exposes:
  GET  /api/config              — active model ref and enabled UI modules
  POST /api/run                 — run ticket summary playbook
  POST /api/intake              — webhook intake: accept a pushed work item (ADR-0015)
  *    /api/channels/wecom/callback — WeCom assist callback (ADR-0019; 404 when unconfigured)
  *    /api/inventory           — Asset CRUD + event log (owned domain, ADR-0017)
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

from ..auth import AuthStore
from ..config import load_config
from ..embedding import resolve_embedding
from ..inventory import InventoryStore
from ..log_buffer import install as install_log_buffer
from ..mcp import McpRegistry, load_mcp_config
from ..memory.lance_store import LanceStore
from ..memory.sqlite_store import SqliteStore
from ..memory.storage_init import init_sqlite
from ..orchestrator.types import load_playbook
from ..providers.registry import make_provider
from ..redaction import Redactor
from ..session.manager import SessionManager
from ..settings_store import SettingsStore
from ..skills import SkillRegistry
from .middleware import AuthMiddleware, ObservabilityMiddleware
from .routes.admin import router as admin_router
from .routes.auth import router as auth_router
from .routes.chat import router as chat_router
from .routes.config import router as config_router
from .routes.doc import router as doc_router
from .routes.harness import router as harness_router
from .routes.health import router as health_router
from .routes.intake import router as intake_router
from .routes.inventory import router as inventory_router
from .routes.iteration import router as iteration_router
from .routes.kb import router as kb_router
from .routes.mcp import router as mcp_router
from .routes.metrics import router as metrics_router
from .routes.models import router as models_router
from .routes.run import router as run_router
from .routes.sandbox import router as sandbox_router
from .routes.sessions import router as sessions_router
from .routes.wecom import router as wecom_router
from .routes.wiki import router as wiki_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise all heavy resources on startup; clean up on shutdown."""
    cfg = load_config()

    playbooks_base = cfg.playbooks_dir or Path("playbooks")
    playbook_id = os.environ.get("OPSPILOT_DEFAULT_PLAYBOOK", "pb_ticket_summary_en")
    playbook = load_playbook(playbooks_base / playbook_id)
    vendor_doc_pb = load_playbook(playbooks_base / "pb_vendor_doc_en")
    request_pb_id = os.environ.get("OPSPILOT_REQUEST_PLAYBOOK", "pb_request_fulfillment_en")
    request_fulfillment_pb = load_playbook(playbooks_base / request_pb_id)
    classify_pb_id = os.environ.get("OPSPILOT_CLASSIFY_PLAYBOOK", "pb_classify_work_item_en")
    classify_pb = load_playbook(playbooks_base / classify_pb_id)

    # Hand-authored runtime skills (ADR-0022) — the chat agent loads them on
    # demand via load_skill; weak models get the best match injected.
    skills = SkillRegistry.load(Path(os.environ.get("OPSPILOT_SKILLS_DIR", "agent_skills")))

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
    inventory = InventoryStore(conn)  # idempotent schema; shares the KB db file
    auth = AuthStore(conn)  # multi-user identity (ADR-0020)
    settings = SettingsStore(conn)  # non-secret admin config (e.g. default model)
    bootstrap_admin = os.environ.get("OPSPILOT_BOOTSTRAP_ADMIN")
    bootstrap_pw = os.environ.get("OPSPILOT_BOOTSTRAP_PASSWORD")
    if bootstrap_admin and bootstrap_pw:
        auth.bootstrap_admin(bootstrap_admin, bootstrap_pw)

    # Embeddings: OpenAI by default, Ollama when asked for or when no OpenAI
    # key is set — chosen once at startup, with a user-facing notice (ADR-0020
    # posture: surface, don't silently degrade). See opspilot.embedding. It is
    # resolved before the vector store so the KB is opened, and tagged, with
    # the embedder actually in use.
    embed_fn, embed_status = resolve_embedding(cfg)

    lance = LanceStore.open_or_create(
        kb_dir / "lancedb",
        dim=768,
        embedding_model=embed_status.model,
        allow_model_mismatch=os.environ.get("OPSPILOT_ALLOW_EMBED_MISMATCH") == "1",
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
    app.state.skills = skills
    # Web search for the chat agent (#120) — gated on a Brave key, since it
    # egresses the query to an external engine. No key → the tool isn't offered.
    from ..websearch import web_search_available

    app.state.web_search_enabled = web_search_available()
    app.state.classify_threshold = float(os.environ.get("OPSPILOT_CLASSIFY_THRESHOLD", "0.7"))
    app.state.vendor_doc_provider = vendor_doc_provider
    app.state.active_model_ref = active_model_ref
    app.state.sqlite = sqlite
    app.state.inventory = inventory
    app.state.auth = auth
    app.state.settings = settings
    app.state.service_token = cfg.api_token  # ADR-0011 bearer → Service token (ADR-0020)
    app.state.lance = lance
    app.state.chat_provider = chat_provider
    app.state.embed_fn = embed_fn
    app.state.embed_status = embed_status
    app.state.session_mgr = session_mgr
    app.state.redactor = redactor
    app.state.mcp_registry = mcp_registry
    app.state.mcp_config_path = mcp_config_path  # where the admin UI writes (ADR-0024)

    yield

    if mcp_registry is not None:
        mcp_registry.close_all()


app = FastAPI(title="OpsPilot API", version="0.2.0", lifespan=lifespan)

# Capture recent logs in memory for the admin log viewer. Installed here (after
# any configure_json_logging, which clears root handlers) so it survives.
install_log_buffer()

# Bearer-token auth (ADR-0011). Added first so it runs INNERMOST: CORS
# preflights short-circuit before it, and Observability still logs 401s.
# Enabled only when a token is configured (env OPSPILOT_API_TOKEN or
# config.yaml api_token) — bare local dev stays friction-free.
_api_token = load_config().api_token
if _api_token:
    app.add_middleware(AuthMiddleware, token=_api_token)

# Allow Svelte dev server (5173) and preview server (4173) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ObservabilityMiddleware)

app.include_router(health_router)  # /health  (no /api prefix — ops endpoints)
app.include_router(metrics_router)  # /metrics
app.include_router(auth_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(run_router, prefix="/api")
app.include_router(intake_router, prefix="/api")
app.include_router(inventory_router, prefix="/api")
app.include_router(doc_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(iteration_router, prefix="/api")
app.include_router(kb_router, prefix="/api")
app.include_router(wiki_router, prefix="/api")
app.include_router(harness_router, prefix="/api")
app.include_router(mcp_router, prefix="/api")
app.include_router(sandbox_router, prefix="/api")
app.include_router(wecom_router, prefix="/api")


def _mount_ui(fastapi_app: FastAPI) -> None:
    """Serve the pre-built web UI as static files (all-in-one image, ADR-0020).

    Mounted last so /api, /health and /metrics always win. The directory is
    ``OPSPILOT_UI_DIR`` (set in the Docker image) or ``web/build`` from a
    local ``pnpm build``; absent (dev with the Vite server) it is skipped.
    """
    from starlette.staticfiles import StaticFiles

    ui_env = os.environ.get("OPSPILOT_UI_DIR")
    ui_dir = Path(ui_env) if ui_env else Path(__file__).resolve().parents[3] / "web" / "build"
    if not (ui_dir / "index.html").is_file():
        return
    # html=True serves index.html for "/"; the app is a single client page,
    # so no deep-route SPA fallback is needed.
    fastapi_app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")


_mount_ui(app)
