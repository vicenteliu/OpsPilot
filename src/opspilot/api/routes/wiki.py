"""Wiki API routes: ingest, query-to-page, lint, promote."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class WikiIngestRequest(BaseModel):
    doc_id: str
    namespace: str = "opspilot:public-kb"
    model: str = "qwen2.5:7b"
    owner: str = "wiki-maintainer@opspilot"


@router.post("/wiki/ingest")
async def wiki_ingest(body: WikiIngestRequest, request: Request) -> dict[str, Any]:
    """Generate a wiki summary page from an already-ingested KB document."""
    state = request.app.state
    cfg = state.cfg

    from ...providers.ollama import OllamaProvider
    from ...wiki.ingest import WikiIngestConfig
    from ...wiki.ingest import ingest as run_wiki_ingest

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        provider = OllamaProvider(base_url=cfg.ollama_base_url)
        wiki_cfg = WikiIngestConfig(
            wiki_root=cfg.home / "wiki",
            namespace=body.namespace,
            owner=body.owner,
            model=body.model,
        )
        return run_wiki_ingest(body.doc_id, sqlite=state.sqlite, provider=provider, config=wiki_cfg)

    result = await loop.run_in_executor(None, _run)

    return {
        "page_id": result.page_id,
        "slug": result.slug,
        "page_path": str(result.page_path),
        "pages_created": result.pages_created,
        "pages_updated": result.pages_updated,
    }


class WikiQueryToPageRequest(BaseModel):
    session_id: str | None = None
    model: str = "qwen2.5:7b"
    owner: str = "wiki-maintainer@opspilot"
    namespace: str = "opspilot:public-kb"
    max_sessions: int = 50


@router.post("/wiki/query-to-page")
async def wiki_query_to_page(body: WikiQueryToPageRequest, request: Request) -> dict[str, Any]:
    """Convert qualifying session responses into wiki synthesis pages."""
    state = request.app.state
    cfg = state.cfg

    from ...providers.ollama import OllamaProvider
    from ...wiki.query_to_page import QueryToPageConfig, query_to_page, scan_and_convert

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        provider = OllamaProvider(base_url=cfg.ollama_base_url)
        qtp_cfg = QueryToPageConfig(
            wiki_root=cfg.home / "wiki",
            namespace=body.namespace,
            owner=body.owner,
            model=body.model,
        )
        if body.session_id:
            result = query_to_page(
                body.session_id,
                session_manager=state.session_mgr,
                provider=provider,
                config=qtp_cfg,
            )
            return {
                "pages_created": 0 if result.skipped else 1,
                "pages_updated": 0,
                "pages": []
                if result.skipped
                else [{"slug": result.slug, "page_id": result.page_id}],
                "skipped": result.skipped,
                "skip_reason": result.skip_reason,
            }
        results = scan_and_convert(
            session_manager=state.session_mgr,
            provider=provider,
            config=qtp_cfg,
            max_sessions=body.max_sessions,
        )
        created = sum(1 for r in results if not r.skipped)
        pages = [{"slug": r.slug, "page_id": r.page_id} for r in results if not r.skipped]
        return {
            "pages_created": created,
            "pages_updated": 0,
            "pages": pages,
            "skipped": False,
            "skip_reason": "",
        }

    return await loop.run_in_executor(None, _run)


@router.get("/wiki/lint")
async def wiki_lint(request: Request) -> dict[str, Any]:
    """Run wiki linter and return all issues."""
    cfg = request.app.state.cfg

    from ...wiki.lint import lint_wiki

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        return lint_wiki(cfg.home / "wiki")

    issues = await loop.run_in_executor(None, _run)

    return {
        "issues": [
            {
                "id": i.id,
                "issue_type": i.issue_type,
                "severity": i.severity,
                "summary": i.summary,
                "page_slug": i.page_slug,
                "detected_at": i.detected_at,
            }
            for i in issues
        ]
    }


@router.get("/wiki/pages")
async def list_wiki_pages(request: Request) -> dict[str, Any]:
    """List all wiki pages from ~/.opspilot/wiki/pages/."""
    cfg = request.app.state.cfg
    pages_dir = cfg.home / "wiki" / "pages"

    from ...wiki.page import read_page

    pages = []
    if pages_dir.is_dir():
        for md_file in sorted(pages_dir.rglob("*.md")):
            try:
                page = read_page(md_file)
                pages.append(
                    {
                        "page_id": page.page_id,
                        "slug": page.slug,
                        "kind": page.kind,
                        "title": page.title,
                        "summary": page.summary,
                        "lifecycle_state": page.lifecycle_state,
                        "language": page.language,
                        "tags": page.tags,
                        "updated_at": page.updated_at,
                    }
                )
            except Exception:  # noqa: BLE001
                pass
    return {"pages": pages, "total": len(pages)}


@router.get("/wiki/pages/{slug}")
async def get_wiki_page(slug: str, request: Request) -> dict[str, Any]:
    """Return full wiki page (frontmatter + body) for the given slug."""
    cfg = request.app.state.cfg
    pages_dir = cfg.home / "wiki" / "pages"

    from fastapi import HTTPException

    from ...wiki.page import read_page

    md_file = pages_dir / f"{slug}.md"
    if not md_file.is_file():
        raise HTTPException(status_code=404, detail=f"Page '{slug}' not found")
    page = read_page(md_file)
    return {
        "page_id": page.page_id,
        "slug": page.slug,
        "kind": page.kind,
        "title": page.title,
        "summary": page.summary,
        "lifecycle_state": page.lifecycle_state,
        "language": page.language,
        "tags": page.tags,
        "updated_at": page.updated_at,
        "body": page.body,
        "outbound_links": page.outbound_links,
        "derived_from": page.derived_from,
        "owner": page.owner,
    }


@router.post("/wiki/promote/{slug}")
async def wiki_promote(slug: str, request: Request) -> dict[str, Any]:
    """Promote a draft/reviewed wiki page to live."""
    cfg = request.app.state.cfg

    from ...wiki.promote import PromoteConfig, promote_page

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        return promote_page(slug, PromoteConfig(wiki_root=cfg.home / "wiki"))

    result = await loop.run_in_executor(None, _run)

    return {
        "slug": slug,
        "old_state": result.old_state,
        "new_state": result.new_state,
        "new_version": result.new_version,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
    }
