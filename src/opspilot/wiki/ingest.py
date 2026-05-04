"""Wiki ingest — turns a KB document into a wiki summary page (PR-19).

Flow:
  1. Fetch KB document + chunks from SQLite.
  2. Call LLM to propose: slug, title, summary, language, tags, body.
  3. Assemble full WikiPage (fill in all technical fields).
  4. Static checks: slug format, summary length, body has required sections.
  5. Write page to ``wiki_root/pages/summary/<slug>.md``.
  6. Update wiki_root/index.md and wiki_root/log.md.
  7. Optionally register the wiki page back to the KB as wiki_synthesis.

query→page and lint are deferred to Stage 4 (PR-24 / PR-23).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import OpsPilotError
from ..memory.sqlite_store import SqliteStore
from ..providers.base import ProviderProtocol
from ..providers.types import Message, SamplingParams
from ..timeutil import now_rfc3339
from .index import WikiLogEntry, append_log, update_index
from .page import WikiPage, make_page_id, write_page

# ── Config / Result ───────────────────────────────────────────────────


@dataclass(frozen=True)
class WikiIngestConfig:
    wiki_root: Path
    namespace: str = "opspilot:public-kb"
    owner: str = "wiki-maintainer@opspilot"
    model: str = "qwen2.5:7b"
    temperature: float = 0.2
    max_tokens: int = 2000
    lifecycle_state: str = "live"
    redaction_rules_version: str = "1.0.0"
    register_to_kb: bool = False  # Stage 4 feature; disabled by default


@dataclass
class WikiIngestResult:
    page_id: str
    slug: str
    page_path: Path
    pages_created: int
    pages_updated: int


class WikiIngestError(OpsPilotError):
    """Raised when wiki ingest cannot complete."""


# ── Prompt ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a wiki maintainer for OpsPilot. Your task is to read a knowledge-base document \
and produce a structured wiki **summary page** in JSON format.

Rules:
- Output ONLY a single JSON object. No markdown fences, no explanation.
- "slug": lowercase, hyphen-separated ASCII or pinyin, 2-80 chars, globally unique.
- "title": human-readable, include the doc language if non-English (e.g. "(中文)").
- "summary": one sentence ≤120 chars; used as the index.md entry.
- "language": "zh-CN", "en", or "mixed".
- "tags": list of ≤6 lowercase topic tags.
- "aliases": list of alternative names (may be empty).
- "body": complete markdown body following the summary-page template:
  ## TL;DR
  (2-4 sentences: what the doc is about and its core claim)

  ## Key claims
  (3-5 bullet points of factual claims, each ≤ 1 sentence)

  ## Implications for our wiki
  (what pages are missing or should be linked; use [[slug]] notation)

  ## Cross-links
  (use "relation → [[slug]]: reason" format; see_also if unsure)

  ## Sources
  (numbered list; use the doc_id and title provided)

  ## Changelog
  - v1.0.0 (YYYY-MM-DD): initial; from <doc_id>

JSON schema:
{
  "slug": "string",
  "title": "string",
  "summary": "string (≤120 chars)",
  "language": "string",
  "tags": ["string"],
  "aliases": ["string"],
  "body": "string (markdown)"
}
"""


def _build_prompt(doc: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    title = doc.get("title") or doc.get("source_path", "")
    doc_id = doc["id"]
    content = "\n\n".join(c["content"] for c in chunks[:20])  # cap at 20 chunks
    return (
        f"Document ID: {doc_id}\n"
        f"Title: {title}\n"
        f"Language: {doc.get('language', 'unknown')}\n"
        f"Classification: {doc.get('classification', 'internal')}\n\n"
        f"--- Document content (chunks) ---\n{content}\n--- end ---\n\n"
        "Please generate the wiki summary page JSON now."
    )


# ── LLM call + parse ──────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,79}$")


def _call_llm(
    prompt: str,
    provider: ProviderProtocol,
    config: WikiIngestConfig,
) -> dict[str, Any]:
    messages = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(role="user", content=prompt),
    ]
    params = SamplingParams(
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    resp = provider.chat(messages, model=config.model, params=params)
    raw = resp.content.strip()

    # Strip optional markdown code fence
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.rstrip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WikiIngestError(f"LLM output is not valid JSON: {exc}\n---\n{raw[:500]}") from exc

    return data


def _validate_proposal(data: dict[str, Any]) -> None:
    """Raise WikiIngestError if the LLM output is malformed."""
    missing = [k for k in ("slug", "title", "summary", "language", "body") if not data.get(k)]
    if missing:
        raise WikiIngestError(f"LLM proposal missing required fields: {missing}")
    slug = data["slug"]
    if not _SLUG_RE.match(slug):
        # Auto-fix common issues: strip spaces, lowercase, replace _ with -
        fixed = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
        fixed = re.sub(r"-+", "-", fixed)
        if _SLUG_RE.match(fixed):
            data["slug"] = fixed
        else:
            raise WikiIngestError(f"Invalid slug from LLM: {slug!r}")
    if len(data["summary"]) > 200:
        data["summary"] = data["summary"][:197] + "..."


# ── Assembly ──────────────────────────────────────────────────────────


def _assemble_page(
    proposal: dict[str, Any],
    doc: dict[str, Any],
    config: WikiIngestConfig,
    now: str,
) -> WikiPage:
    slug = proposal["slug"]
    body = proposal["body"].strip()
    page_id = make_page_id(slug, body)

    source_sha256 = doc.get("content_hash") or ""
    if not source_sha256.startswith("sha256:"):
        source_sha256 = f"sha256:{source_sha256}"

    return WikiPage(
        page_id=page_id,
        slug=slug,
        kind="summary",
        title=proposal["title"],
        summary=proposal["summary"],
        namespace=config.namespace,
        classification=doc.get("classification", "internal"),
        language=proposal.get("language", "en"),
        version="1.0.0",
        created_at=now,
        updated_at=now,
        tags=proposal.get("tags") or [],
        aliases=proposal.get("aliases") or [],
        derived_from={
            "sources": [
                {
                    "kind": "kb_document",
                    "ref": doc["id"],
                    "sha256": source_sha256,
                    "line_start": None,
                    "line_end": None,
                }
            ],
            "parent_pages": [],
        },
        outbound_links=[],
        inbound_link_count=0,
        redacted=True,
        redaction_rules_version=config.redaction_rules_version,
        lifecycle_state=config.lifecycle_state,
        owner=config.owner,
        extensions={
            "summary": {
                "source_doc_id": doc["id"],
                "source_uri": doc.get("source_url"),
            }
        },
        body=body,
    )


# ── Public entry point ────────────────────────────────────────────────


def ingest(
    doc_id: str,
    *,
    sqlite: SqliteStore,
    provider: ProviderProtocol,
    config: WikiIngestConfig,
) -> WikiIngestResult:
    """Generate (or update) a wiki summary page from a KB document.

    Raises :class:`WikiIngestError` if the document is missing, the LLM
    output is invalid, or a static check fails.
    """
    # 1. Fetch KB document
    doc = sqlite.get_document(doc_id)
    if doc is None:
        raise WikiIngestError(f"KB document not found: {doc_id}")

    # 2. Fetch chunks (up to 20 for context)
    chunks = sqlite.get_chunks_by_document_id(doc_id)

    # 3-4. Call LLM and validate
    prompt = _build_prompt(doc, chunks)
    proposal = _call_llm(prompt, provider, config)
    _validate_proposal(proposal)

    # 5. Assemble full page
    now = now_rfc3339()
    page = _assemble_page(proposal, doc, config, now)

    # 6. Determine output path
    pages_dir = config.wiki_root / "pages" / "summary"
    page_path = pages_dir / f"{page.slug}.md"
    is_update = page_path.exists()

    write_page(page, page_path)

    # 7. Update index.md and log.md
    update_index(config.wiki_root, page)
    append_log(
        config.wiki_root,
        WikiLogEntry(
            op="ingest",
            subject=doc_id,
            pages_created=0 if is_update else 1,
            pages_updated=1 if is_update else 0,
            notes=f"slug={page.slug}",
        ),
    )

    return WikiIngestResult(
        page_id=page.page_id,
        slug=page.slug,
        page_path=page_path,
        pages_created=0 if is_update else 1,
        pages_updated=1 if is_update else 0,
    )
