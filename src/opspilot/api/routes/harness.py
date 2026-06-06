"""POST /api/harness/run route."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class HarnessRunRequest(BaseModel):
    fixture_path: str
    golden_path: str
    playbook_dir: str
    owner: str = "harness@opspilot"
    embed_model_short: str = "nomic-embed-text-v2-moe"
    output_path: str | None = None


@router.post("/harness/run")
async def harness_run(body: HarnessRunRequest, request: Request) -> dict[str, Any]:
    """Run a single fixture through the evaluation harness."""
    state = request.app.state
    cfg = state.cfg

    from ...harness import load_fixture, load_golden, run_harness
    from ...memory.lance_store import LanceStore
    from ...memory.sqlite_store import SqliteStore
    from ...memory.storage_init import init_sqlite
    from ...orchestrator.types import load_playbook
    from ...providers import make_provider

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        fixture = load_fixture(Path(body.fixture_path))
        golden = load_golden(Path(body.golden_path))
        playbook = load_playbook(Path(body.playbook_dir))

        kb_dir = cfg.home / "kb"
        kb_dir.mkdir(parents=True, exist_ok=True)
        sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
        lance = LanceStore.open_or_create(
            kb_dir / "lancedb", dim=768, embedding_model=cfg.embed_model
        )
        embed_provider = make_provider("ollama-local", base_url=cfg.ollama_base_url)

        def embed_fn(text: str) -> list[float]:
            return embed_provider.embed([text], model=body.embed_model_short)[0]

        chat_provider = make_provider(
            playbook.model.provider_id,
            kind=playbook.model.kind,
            api_key=cfg.anthropic_api_key,
        )

        result = run_harness(
            fixture=fixture,
            golden=golden,
            playbook=playbook,
            provider=chat_provider,
            embed_fn=embed_fn,
            sqlite_store=sqlite,
            lance_store=lance,
            session_manager=state.session_mgr,
            redactor=state.redactor,
            owner=body.owner,
        )

        if body.output_path:
            import json

            out = Path(body.output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(result.__dict__, default=str) + "\n")

        return result

    result = await loop.run_in_executor(None, _run)

    return {
        "fixture_id": result.fixture_id,
        "playbook_ref": result.playbook_ref,
        "model_ref": result.model_ref,
        "passed": result.passed,
        "scores": result.scores,
        "latency_ms": result.latency_ms,
    }
