"""Minimal built-in web search for the chat agent (#120).

Self-hosted — no external MCP server. Queries the **Brave Search API** and
returns a short list of ``{title, url, snippet}``. It is gated on a configured
key (``BRAVE_API_KEY``) because a raw query egresses to an external engine:
OpsPilot redacts KB/model content, but a search string still leaves the
deployment. The HTTP backend is swappable via ``http_get`` for testing.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import httpx

from .providers.types import ToolDef

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

# A getter takes (query, timeout_s) and returns the parsed JSON dict.
HttpGet = Callable[[str, float], dict[str, Any]]


def _brave_key() -> str | None:
    # Prefer the conventional upper-case name; also accept the mixed-case one
    # some deployments (and our .env) use.
    return os.environ.get("BRAVE_API_KEY") or os.environ.get("Brave_API_KEY")  # noqa: SIM112


def web_search_available() -> bool:
    """True when web search is configured (a Brave key is set)."""
    return bool(_brave_key())


def _default_get(query: str, timeout_s: float) -> dict[str, Any]:
    key = _brave_key()
    if not key:
        raise RuntimeError("BRAVE_API_KEY not set")
    resp = httpx.get(
        _BRAVE_URL,
        params={"q": query, "count": 5},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=timeout_s,
    )
    resp.raise_for_status()
    return dict(resp.json())


def web_search(
    query: str,
    *,
    max_results: int = 5,
    timeout_s: float = 10.0,
    http_get: HttpGet | None = None,
) -> list[dict[str, str]]:
    """Return up to *max_results* ``{title, url, snippet}`` hits; [] on any failure."""
    q = query.strip()
    if not q:
        return []
    getter = http_get or _default_get
    try:
        data = getter(q, timeout_s)
    except Exception:  # noqa: BLE001 — search is best-effort; the agent proceeds without it
        return []

    results: list[dict[str, str]] = []
    for r in (data.get("web", {}) or {}).get("results", []) or []:
        if len(results) >= max_results:
            break
        if isinstance(r, dict) and r.get("url"):
            results.append(
                {
                    "title": str(r.get("title") or r.get("url")),
                    "url": str(r["url"]),
                    "snippet": str(r.get("description") or ""),
                }
            )
    return results


def make_web_search_tool(
    *, max_results: int = 5
) -> tuple[ToolDef, Callable[[dict[str, Any]], dict[str, Any]]]:
    """Return ``(tool_def, handler)`` for the ``web_search`` tool."""
    tool = ToolDef(
        name="web_search",
        description=(
            "Search the public web for current information not in the knowledge base "
            "(vendor advisories, error messages, recent changes). Returns titles, URLs, "
            "and snippets — cite the URLs you rely on."
        ),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Web search query.", "minLength": 1}
            },
        },
    )

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        return {"results": web_search(str(args.get("query", "")), max_results=max_results)}

    return tool, handler
