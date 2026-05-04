"""Wiki query→page engine (PR-24).

Converts a qualifying session response into a new wiki page (kind=synthesis
or kind=summary) and writes it under ``wiki_root/pages/<kind>/<slug>.md``.

Trigger conditions (any one suffices):
  * Session contains ≥ 2 ``kb_search`` tool calls  (synthesis-worthy)
  * Session trace has a ``user_action.accept`` event  (user approved)

Safety gates (all must pass):
  * Session status == "archived"
  * Session sensitivity != "restricted"
  * No existing page with the same slug already in wiki_root (skip, not error)

The page is always written with ``lifecycle_state=draft``; human review
promotes it to ``live``.  This follows the query-to-page recipe template.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import OpsPilotError
from ..providers.base import ProviderProtocol
from ..providers.types import Message, SamplingParams
from ..session.manager import SessionManager
from ..timeutil import now_rfc3339
from .index import WikiLogEntry, append_log, update_index
from .page import WikiPage, make_page_id, write_page

# ── Config ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueryToPageConfig:
    wiki_root: Path
    namespace: str = "opspilot:public-kb"
    owner: str = "wiki-maintainer@opspilot"
    model: str = "qwen2.5:7b"
    temperature: float = 0.2
    max_tokens: int = 2000
    min_kb_searches: int = 2  # trigger: ≥ N kb_search calls
    lifecycle_state: str = "draft"
    redaction_rules_version: str = "1.0.0"


# ── Result / Error ─────────────────────────────────────────────────────────────


@dataclass
class QueryToPageResult:
    session_id: str
    slug: str
    page_id: str
    page_path: Path
    trigger: str           # "kb_search_count" | "user_accept"
    skipped: bool = False  # True when page already existed or session not qualified
    skip_reason: str = ""


class QueryToPageError(OpsPilotError):
    """Raised when query→page cannot complete."""


# ── Trace reading ─────────────────────────────────────────────────────────────

_KB_TOOL_NAMES = {"kb_search", "kb.search"}


@dataclass
class _TraceData:
    final_response: str            # content of the last stop-or-final response
    kb_hits: list[dict[str, Any]]  # deduplicated KB hits from tool_result events
    kb_search_count: int           # number of kb_search tool calls
    has_user_accept: bool          # any user_action.accept event


def _read_trace(trace_path: Path) -> _TraceData:
    """Parse ``trace.jsonl`` and extract query→page relevant data."""
    final_response = ""
    kb_hits: list[dict[str, Any]] = []
    seen_chunks: set[str] = set()
    kb_search_count = 0
    has_user_accept = False

    if not trace_path.is_file():
        return _TraceData(final_response, kb_hits, kb_search_count, has_user_accept)

    events = []
    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue

    for ev in events:
        t = ev.get("type")

        if t == "tool_call" and ev.get("tool") in _KB_TOOL_NAMES:
            kb_search_count += 1

        elif t == "tool_result" and ev.get("tool") in _KB_TOOL_NAMES:
            stdout = ev.get("stdout_ref") or ""
            hits = _parse_kb_hits(stdout, trace_path.parent)
            for h in hits:
                cid = h.get("chunk_id") or h.get("id") or ""
                if cid and cid not in seen_chunks:
                    seen_chunks.add(cid)
                    kb_hits.append(h)

        elif t == "response":
            content = ev.get("content") or ""
            if content:
                # Keep the last non-empty response (may be overwritten)
                final_response = content

        elif t == "user_action" and ev.get("action") == "accept":
            has_user_accept = True

    return _TraceData(final_response, kb_hits, kb_search_count, has_user_accept)


def _parse_kb_hits(stdout_ref: str, session_dir: Path) -> list[dict[str, Any]]:
    """Parse KB hits from ``stdout_ref``.

    Supports two formats:
      - Inline JSON string (new orchestrator, ≤8000 chars)
      - File path relative to repo root (legacy example traces)
    """
    if not stdout_ref:
        return []

    # Try parsing as JSON first
    try:
        data = json.loads(stdout_ref)
        return list(data.get("hits") or [])
    except (json.JSONDecodeError, AttributeError):
        pass

    # Try as a file path (relative to CWD or absolute)
    candidate = Path(stdout_ref)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.is_file():
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            return list(data.get("hits") or [])
        except Exception:  # noqa: BLE001
            pass

    return []


# ── Qualification ─────────────────────────────────────────────────────────────


def _qualify(
    session_id: str,
    sm: SessionManager,
    config: QueryToPageConfig,
) -> tuple[str, str]:  # (trigger, skip_reason) — trigger="" means skip
    """Return (trigger_name, "") if qualified, ("", skip_reason) if not."""
    try:
        sess = sm.load(session_id)
    except Exception as exc:  # noqa: BLE001
        return "", f"failed to load session: {exc}"

    if sess.status != "archived":
        return "", f"session status is '{sess.status}', not 'archived'"

    if sess.sensitivity == "restricted":
        return "", "session sensitivity is 'restricted' — blocked by safety gate"

    trace_path = sm.session_dir(session_id) / "trace.jsonl"
    data = _read_trace(trace_path)

    if not data.final_response:
        return "", "no response content found in trace"

    if data.kb_search_count >= config.min_kb_searches:
        return "kb_search_count", ""

    if data.has_user_accept:
        return "user_accept", ""

    return "", (
        f"does not qualify: kb_search_count={data.kb_search_count} < {config.min_kb_searches}"
        " and no user_action.accept found"
    )


# ── LLM prompt ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a wiki maintainer for OpsPilot. Your task is to read a session response \
and the KB chunks it drew from, then produce a structured wiki **synthesis page** in JSON format.

Rules:
- Output ONLY a single JSON object. No markdown fences, no explanation.
- "slug": lowercase, hyphen-separated ASCII, 2-80 chars, globally unique.
- "title": concise, human-readable.
- "summary": one sentence ≤ 120 chars; used as the index.md entry.
- "language": "zh-CN", "en", or "mixed".
- "tags": list of ≤ 6 lowercase topic tags.
- "aliases": list of alternative names (may be empty).
- "body": complete markdown body:

  ## Thesis
  (1-2 sentences: the core claim the session response establishes)

  ## Evidence
  (3-5 bullet points; each must cite a KB chunk using its chunk_id)

  ## Counter-evidence
  (what this response does NOT address or where uncertainty remains)

  ## Gaps
  (wiki pages that should exist but don't; mention [[slug]] if known)

  ## Cross-links
  (use "relation → [[slug]]: reason"; see_also if unsure)

  ## Sources
  (numbered list of chunk_id + document_id + short description)

  ## Changelog
  - v1.0.0 (YYYY-MM-DD): initial; from session <session_id>

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

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,79}$")


def _build_user_message(
    session_id: str,
    response: str,
    kb_hits: list[dict[str, Any]],
) -> str:
    chunks_text = "\n\n".join(
        f"[{h.get('chunk_id', '?')}] (doc={h.get('document_id', '?')})\n{h.get('content', '')}"
        for h in kb_hits[:10]
    )
    return (
        f"Session ID: {session_id}\n\n"
        f"--- Session response ---\n{response[:3000]}\n--- end response ---\n\n"
        f"--- KB chunks cited ---\n{chunks_text or '(none)'}\n--- end chunks ---\n\n"
        "Please generate the wiki synthesis page JSON now."
    )


# ── LLM call + validate ───────────────────────────────────────────────────────


def _call_llm(
    user_msg: str,
    provider: ProviderProtocol,
    config: QueryToPageConfig,
) -> dict[str, Any]:
    messages = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(role="user", content=user_msg),
    ]
    params = SamplingParams(temperature=config.temperature, max_tokens=config.max_tokens)
    resp = provider.chat(messages, model=config.model, params=params)
    raw = resp.content.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.rstrip())
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise QueryToPageError(f"LLM output is not valid JSON: {exc}\n---\n{raw[:500]}") from exc


def _validate_and_fix(data: dict[str, Any], session_id: str) -> None:
    missing = [k for k in ("slug", "title", "summary", "language", "body") if not data.get(k)]
    if missing:
        raise QueryToPageError(f"LLM proposal missing required fields: {missing}")
    slug = data["slug"]
    if not _SLUG_RE.match(slug):
        fixed = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
        fixed = re.sub(r"-+", "-", fixed)
        if _SLUG_RE.match(fixed):
            data["slug"] = fixed
        else:
            raise QueryToPageError(f"Invalid slug from LLM: {slug!r}")
    if len(data["summary"]) > 200:
        data["summary"] = data["summary"][:197] + "..."
    # Substitute session_id placeholder in Changelog
    data["body"] = data["body"].replace("<session_id>", session_id)


# ── Assembly ──────────────────────────────────────────────────────────────────


def _assemble_page(
    proposal: dict[str, Any],
    session_id: str,
    kb_hits: list[dict[str, Any]],
    config: QueryToPageConfig,
    now: str,
    kind: str,
) -> WikiPage:
    slug = proposal["slug"]
    body = proposal["body"].strip()
    page_id = make_page_id(slug, body)
    sources = [
        {
            "kind": "session_response",
            "ref": session_id,
            "sha256": "sha256:",
            "line_start": None,
            "line_end": None,
        }
    ]
    for h in kb_hits[:10]:
        sources.append(
            {
                "kind": "kb_chunk",
                "ref": h.get("chunk_id") or h.get("id", ""),
                "sha256": "sha256:",
                "line_start": None,
                "line_end": None,
            }
        )
    return WikiPage(
        page_id=page_id,
        slug=slug,
        kind=kind,
        title=proposal["title"],
        summary=proposal["summary"],
        namespace=config.namespace,
        classification="internal",
        language=proposal.get("language", "en"),
        version="1.0.0",
        created_at=now,
        updated_at=now,
        tags=proposal.get("tags") or [],
        aliases=proposal.get("aliases") or [],
        derived_from={"sources": sources, "parent_pages": []},
        outbound_links=[],
        inbound_link_count=0,
        redacted=True,
        redaction_rules_version=config.redaction_rules_version,
        lifecycle_state=config.lifecycle_state,
        owner=config.owner,
        extensions={"query_to_page": {"session_id": session_id}},
        body=body,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def query_to_page(
    session_id: str,
    *,
    session_manager: SessionManager,
    provider: ProviderProtocol,
    config: QueryToPageConfig,
) -> QueryToPageResult:
    """Convert a qualifying session into a wiki synthesis page.

    Returns a :class:`QueryToPageResult` with ``skipped=True`` when the
    session does not qualify or a page for the same slug already exists.
    Raises :class:`QueryToPageError` only for unrecoverable errors (bad
    LLM output, I/O failures).
    """
    # 1. Qualify
    trigger, skip_reason = _qualify(session_id, session_manager, config)
    if not trigger:
        return QueryToPageResult(
            session_id=session_id,
            slug="",
            page_id="",
            page_path=Path("."),
            trigger="",
            skipped=True,
            skip_reason=skip_reason,
        )

    # 2. Extract trace data
    trace_path = session_manager.session_dir(session_id) / "trace.jsonl"
    data = _read_trace(trace_path)

    # 3. Determine page kind
    kind = "synthesis" if len(data.kb_hits) >= 2 else "summary"

    # 4. Build LLM prompt and call
    user_msg = _build_user_message(session_id, data.final_response, data.kb_hits)
    proposal = _call_llm(user_msg, provider, config)
    _validate_and_fix(proposal, session_id)

    # 5. Check for slug collision across all kind subdirectories
    slug = proposal["slug"]
    existing = list(config.wiki_root.glob(f"pages/*/{slug}.md"))
    if existing:
        return QueryToPageResult(
            session_id=session_id,
            slug=slug,
            page_id="",
            page_path=existing[0],
            trigger=trigger,
            skipped=True,
            skip_reason=f"page '{slug}' already exists at {existing[0]}",
        )

    pages_dir = config.wiki_root / "pages" / kind
    page_path = pages_dir / f"{slug}.md"

    # 6. Assemble and write
    now = now_rfc3339()
    page = _assemble_page(proposal, session_id, data.kb_hits, config, now, kind)
    write_page(page, page_path)

    # 7. Update index + log
    update_index(config.wiki_root, page)
    append_log(
        config.wiki_root,
        WikiLogEntry(
            op="query_to_page",
            subject=session_id,
            pages_created=1,
            pages_updated=0,
            notes=f"slug={slug} trigger={trigger}",
        ),
    )

    return QueryToPageResult(
        session_id=session_id,
        slug=slug,
        page_id=page.page_id,
        page_path=page_path,
        trigger=trigger,
        skipped=False,
    )


def scan_and_convert(
    *,
    session_manager: SessionManager,
    provider: ProviderProtocol,
    config: QueryToPageConfig,
    max_sessions: int = 50,
) -> list[QueryToPageResult]:
    """Scan recent archived sessions and convert all qualifying ones.

    Processes up to *max_sessions* most-recent sessions (newest first).
    Skipped sessions are included in the result list with ``skipped=True``.
    """
    session_ids = session_manager.list()
    results: list[QueryToPageResult] = []
    for sid in reversed(session_ids[-max_sessions:]):
        results.append(query_to_page(sid, session_manager=session_manager, provider=provider, config=config))
    return results
