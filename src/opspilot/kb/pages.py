"""Handbook pages from kb_search hits: one per page, its best hit as the excerpt.

Decision 9's candidates on the label set (#226) and the run's ordering of a
Work item's pages for a person (#286) are built here, so an engine is shown
the same thing in both: the Work item, then the page's title, path and
excerpt.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Final

EXCERPT_CHARS: Final = 600


def pages_from_hits(
    hits: Sequence[Any], describe: Callable[[str], dict[str, Any]]
) -> list[dict[str, Any]]:
    """The hits grouped by page in rank order, each page once with its best hit."""
    pages: dict[str, dict[str, Any]] = {}
    for hit in hits:
        if hit.document_id not in pages:
            pages[hit.document_id] = {
                **describe(hit.document_id),
                "document_id": hit.document_id,
                "excerpt": hit.content[:EXCERPT_CHARS],
            }
    return list(pages.values())


def page_state(state: str, page: dict[str, Any]) -> str:
    """The Work item as an engine is shown it, with one candidate page after it."""
    shown = f"Handbook page: {page['title']} ({page['source_path']})\n{page['excerpt']}"
    return f"{state}\n\n{shown}"
