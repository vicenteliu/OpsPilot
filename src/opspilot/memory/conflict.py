"""KB conflict detection and resolution.

Conflict lifecycle:
  open → a_wins | b_wins | merged | dismissed

Detection is run after each document is ingested. For every new chunk we
query LanceDB for similar chunks from *other* documents. Pairs whose cosine
similarity exceeds the threshold are inserted into ``kb_conflicts``.

conflict_type assignment:
  temporal_supersede  — doc A is clearly newer than doc B (valid_from diff ≥ 30 days)
  scope_overlap       — high similarity but no clear temporal ordering
  direct_contradiction — content contains opposite boolean cues (heuristic)
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .lance_store import LanceStore
    from .sqlite_store import SqliteStore

from datetime import UTC

from ..timeutil import now_rfc3339

# cosine similarity threshold to flag a pair as a potential conflict
DEFAULT_SIMILARITY_THRESHOLD = 0.82

# keyword pairs that suggest direct contradiction
_CONTRADICTION_PAIRS = [
    (r"\bdo not\b", r"\bdo\b"),
    (r"\bdisabled?\b", r"\benabled?\b"),
    (r"\bfails?\b", r"\bsucceeds?\b"),
    (r"\bnot supported\b", r"\bsupported\b"),
    (r"禁用", r"启用"),  # CJK: no \b — word boundaries don't apply
    (r"不支持", r"支持"),
    (r"不允许", r"允许"),
]


@dataclass
class ConflictRecord:
    id: str
    chunk_a_id: str
    chunk_b_id: str
    doc_a_id: str
    doc_b_id: str
    conflict_type: str
    similarity: float
    status: str
    resolved_by: str | None
    resolved_at: str | None
    resolution_note: str | None
    detected_at: str
    # enriched fields (joined from other tables)
    doc_a_title: str = ""
    doc_b_title: str = ""
    doc_a_valid_from: str | None = None
    doc_b_valid_from: str | None = None
    chunk_a_content: str = ""
    chunk_b_content: str = ""


def _has_contradiction(text_a: str, text_b: str) -> bool:
    """Return True if text_a and text_b contain opposing keyword cues."""
    text_a_l = text_a.lower()
    text_b_l = text_b.lower()
    for pattern_a, pattern_b in _CONTRADICTION_PAIRS:
        if re.search(pattern_a, text_a_l) and re.search(pattern_b, text_b_l):
            return True
        if re.search(pattern_b, text_a_l) and re.search(pattern_a, text_b_l):
            return True
    return False


def _classify_conflict(
    doc_a_valid_from: str | None,
    doc_b_valid_from: str | None,
    content_a: str,
    content_b: str,
) -> str:
    if doc_a_valid_from and doc_b_valid_from:
        try:
            from datetime import datetime

            da = datetime.strptime(doc_a_valid_from[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
            db = datetime.strptime(doc_b_valid_from[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
            diff_days = abs((da - db).days)
            if diff_days >= 30:
                return "temporal_supersede"
        except (ValueError, AttributeError):
            pass

    if _has_contradiction(content_a, content_b):
        return "direct_contradiction"

    return "scope_overlap"


def detect_and_store_conflicts(
    *,
    new_doc_id: str,
    new_chunks: list[dict],
    lance: LanceStore,
    sqlite: SqliteStore,
    embed_fn: Callable[[str], list[float]],
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> int:
    """Detect conflicts for *new_chunks* against the existing KB.

    Queries LanceDB for similar chunks, skips same-document results, and
    inserts new ``kb_conflicts`` rows for any pair exceeding the threshold.

    Returns the number of new conflict records created.
    """
    doc_cache: dict[str, dict] = {}
    created = 0

    for chunk in new_chunks:
        content = chunk.get("content", "")
        if not content or len(content) < 20:
            continue

        vec = embed_fn(content)
        # Retrieve slightly more candidates so we have enough after filtering same-doc
        neighbors = lance.ann_search(vec, top_k=10)

        for nb in neighbors:
            if nb.document_id == new_doc_id:
                continue
            if nb.score < similarity_threshold:
                continue

            # Deterministic conflict id based on sorted chunk pair
            pair_key = "_".join(sorted([chunk["id"], nb.chunk_id]))
            conf_id = f"conf_{hashlib.sha256(pair_key.encode()).hexdigest()[:8]}"

            # Skip if already exists
            if sqlite.get_conflict(conf_id) is not None:
                continue

            # Fetch doc metadata for type classification
            doc_a = doc_cache.setdefault(new_doc_id, sqlite.get_document(new_doc_id) or {})
            doc_b = doc_cache.setdefault(nb.document_id, sqlite.get_document(nb.document_id) or {})

            # Fetch neighbor chunk content for contradiction heuristic
            nb_chunk = sqlite.get_chunk(nb.chunk_id)
            content_b = (nb_chunk or {}).get("content", "") or ""

            conflict_type = _classify_conflict(
                doc_a.get("valid_from"),
                doc_b.get("valid_from"),
                content,
                content_b,
            )

            sqlite.upsert_conflict(
                {
                    "id": conf_id,
                    "chunk_a_id": chunk["id"],
                    "chunk_b_id": nb.chunk_id,
                    "doc_a_id": new_doc_id,
                    "doc_b_id": nb.document_id,
                    "conflict_type": conflict_type,
                    "similarity": nb.score,
                    "status": "open",
                    "detected_at": now_rfc3339(),
                }
            )
            created += 1

    return created


def resolve_conflict(
    conflict_id: str,
    *,
    resolution: str,
    resolved_by: str,
    note: str = "",
    sqlite: SqliteStore,
) -> None:
    """Apply a resolution to a conflict record.

    Also marks the losing chunk as superseded when resolution is a_wins/b_wins.
    """
    valid = {"a_wins", "b_wins", "merged", "dismissed"}
    if resolution not in valid:
        raise ValueError(f"resolution must be one of {valid}")

    conf = sqlite.get_conflict(conflict_id)
    if conf is None:
        raise KeyError(f"Conflict {conflict_id} not found")

    sqlite.update_conflict_status(
        conflict_id,
        status=resolution,
        resolved_by=resolved_by,
        resolved_at=now_rfc3339(),
        resolution_note=note,
    )

    # Mark superseded chunk
    if resolution == "a_wins":
        sqlite.mark_chunk_superseded(conf["chunk_b_id"], superseded_by=conf["chunk_a_id"])
    elif resolution == "b_wins":
        sqlite.mark_chunk_superseded(conf["chunk_a_id"], superseded_by=conf["chunk_b_id"])
