"""LLM-callable tool wrappers.

PR-7 ships one tool: ``kb_search``. It bridges the LLM tool-call protocol
(OpenAI-compatible JSON-schema args) to PR-4's :func:`kb_search`.

Design:

* The tool returns a JSON-shaped dict the LLM can consume verbatim.
* Citations include ``source_path / line_start / line_end / heading_path``
  so the model can populate the ``citations[]`` array of
  ``ticket_summary_v1`` without inventing fields.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..memory.lance_store import LanceStore
from ..memory.retrieval import Hit, kb_search
from ..memory.sqlite_store import SqliteStore
from ..providers.types import ToolDef

# ── Hit projection used in tool output ───────────────────────────────


@dataclass(frozen=True)
class KBSearchHit:
    """Subset of fields the LLM needs for ticket_summary citations."""

    chunk_id: str
    document_id: str
    score: float
    content: str
    citation: dict[str, Any]
    has_open_conflicts: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "score": self.score,
            "content": self.content,
            "citation": dict(self.citation),
        }
        if self.has_open_conflicts:
            d["has_open_conflicts"] = True
        return d


# ── Tool factory ─────────────────────────────────────────────────────


def make_kb_search_tool(
    *,
    sqlite: SqliteStore,
    lance: LanceStore,
    embed_fn: Callable[[str], list[float]],
    default_top_k: int = 5,
    namespace: str | None = None,
    classification: str | None = None,
) -> tuple[ToolDef, Callable[[dict[str, Any]], dict[str, Any]]]:
    """Return ``(tool_def, handler)`` for the ``kb_search`` tool.

    The :class:`ToolDef` is what we hand to the provider's ``chat(tools=...)``
    argument; the handler is invoked with the LLM-supplied ``args`` dict
    after a ``tool_call`` event arrives, and its return value is what we
    serialise into the corresponding ``tool_result.stdout_ref``.
    """
    tool = ToolDef(
        name="kb_search",
        description=(
            "Hybrid (vector + FTS5) retrieval over the OpsPilot KB. "
            "Use it to find SOP / runbook chunks relevant to the ticket. "
            "Returns up to top_k hits, each with chunk_id, document_id, "
            "the chunk content, and a citation block "
            "(source_path/line_start/line_end/heading_path) to plug into "
            "your final ticket_summary_v1 JSON."
        ),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language query (zh/en).",
                    "minLength": 1,
                },
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": default_top_k,
                },
            },
        },
    )

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        if not query:
            return {"hits": [], "_error": "empty query"}
        top_k = int(args.get("top_k", default_top_k))

        hits: list[Hit] = kb_search(
            query,
            sqlite=sqlite,
            lance=lance,
            embed_fn=embed_fn,
            top_k=top_k,
            namespace=namespace,
            classification=classification,
        )

        out_hits: list[dict[str, Any]] = []
        for h in hits:
            row = sqlite.get_chunk(h.chunk_id) or {}
            doc = sqlite.get_document(h.document_id) or {}
            citation = {
                "source_path": doc.get("source_path"),
                "line_start": row.get("line_start"),
                "line_end": row.get("line_end"),
                "heading_path": row.get("heading_path_json") or [],
                "anchor": row.get("anchor"),
            }
            out_hits.append(
                KBSearchHit(
                    chunk_id=h.chunk_id,
                    document_id=h.document_id,
                    score=h.score,
                    content=h.content or "",
                    citation=citation,
                    has_open_conflicts=h.has_open_conflicts,
                ).to_dict()
            )

        result: dict[str, Any] = {"hits": out_hits, "query": query}

        # Surface a top-level warning when any source document has unresolved
        # conflicts so the LLM can mention this caveat in its final answer.
        conflicted_docs = {
            h.document_id for h in hits if h.has_open_conflicts
        }
        if conflicted_docs:
            result["_conflict_warning"] = (
                f"{len(conflicted_docs)} source document(s) have unresolved "
                "KB conflicts. The information may be inconsistent or outdated. "
                "Inform the user that the answer should be verified by a human."
            )

        return result

    return tool, handler


def render_tool_result(payload: dict[str, Any]) -> str:
    """Serialise a tool result dict for trace + LLM consumption.

    Uses ensure_ascii=False so the model sees the original CJK content
    (rather than \\uXXXX escapes that hurt prompt comprehension).
    """
    return json.dumps(payload, ensure_ascii=False)
