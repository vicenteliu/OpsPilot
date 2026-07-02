"""Hybrid retrieval over SQLite (FTS5 / BM25) + LanceDB (cosine ANN).

Fusion uses **weighted Reciprocal Rank Fusion** per ``docs/specs/memory/SPEC.md §156``::

    rrf_score(chunk) =   vector_weight  * 1 / (k + rank_vector(chunk))
                       + keyword_weight * 1 / (k + rank_fts(chunk))

with default ``k=60`` (Cormack et al. 2009), ``vector_weight=0.6`` and
``keyword_weight=0.4``. Plain unweighted RRF is the special case
``vector_weight = keyword_weight``. Weights default to spec values; expose
overrides for callers that want to tune.

Embedding inference is **injected** as a callable (``embed_fn``); this
module never imports a provider. PR-7 wires the real provider in:

    from opspilot.providers import make_provider
    provider = make_provider("ollama-local")
    embed_fn = lambda q: provider.embed([q], model="nomic-embed-text-v2-moe")[0]

PR-4 tests use a deterministic mock ``embed_fn``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final

from .lance_store import LanceStore
from .sqlite_store import SqliteStore

# FTS5 treats ``:``, ``[``, ``]``, ``"``, ``^``, ``*``, ``NEAR``, parens as
# syntax. A natural-language query containing redaction placeholders
# (e.g. ``[REDACTED:role:11111111]``) crashes with
# ``OperationalError: no such column: role`` when handed verbatim. We
# tokenise on word chars + CJK ideographs and feed each token as a quoted
# phrase, preserving FTS5's implicit-AND semantics.
_FTS_TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)


def _safe_fts_query(q: str) -> str:
    """Sanitise an arbitrary string for FTS5 ``MATCH``.

    Returns a phrase-AND expression of the form ``"tok1" "tok2" ...``.
    Empty input → ``""`` (which fts_search short-circuits via its NULL guard).
    """
    tokens = _FTS_TOKEN_RE.findall(q)
    return " ".join(f'"{t}"' for t in tokens)


# RRF constant — Cormack et al. (2009). Higher k = flatter weighting.
RRF_K: Final[int] = 60

# Source-authority tie-breaker: higher rank wins when RRF scores are equal.
_AUTHORITY_RANK: Final[dict[str, int]] = {
    "official": 3,
    "vendor": 2,
    "internal": 1,
    "unverified": 0,
}

# Default mixing weights from docs/specs/memory/SPEC.md §156. Vector slightly heavier
# because dense retrieval generalises across paraphrase + cross-language;
# keyword catches exact-token hits that embeddings miss.
DEFAULT_VECTOR_WEIGHT: Final[float] = 0.6
DEFAULT_KEYWORD_WEIGHT: Final[float] = 0.4

EmbedFn = Callable[[str], list[float]]


@dataclass(frozen=True)
class Hit:
    """One fused retrieval result.

    ``score`` is the RRF score (higher = better; not directly comparable
    across queries because it depends on the sizes of the two input
    lists). ``rank_vector`` / ``rank_fts`` expose the per-source rank for
    debugging — ``None`` means the chunk did not appear in that source's
    top-k. ``valid_from`` is ISO8601 and used as a tie-breaker (newer wins).
    """

    chunk_id: str
    score: float
    rank_vector: int | None
    rank_fts: int | None
    document_id: str
    namespace: str
    content: str | None
    valid_from: str | None = None
    has_open_conflicts: bool = False
    source_authority: str | None = None


def kb_search(
    query: str,
    *,
    sqlite: SqliteStore,
    lance: LanceStore,
    embed_fn: EmbedFn,
    top_k: int = 5,
    candidate_k: int = 20,
    namespace: str | None = None,
    classification: str | None = None,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
    exclude_superseded: bool = True,
) -> list[Hit]:
    """Hybrid search over the KB. Returns top-k chunks fused by weighted RRF.

    Args:
        query:           User query (assumed already redacted by caller).
        sqlite:          Open ``SqliteStore`` for FTS5 + chunk metadata.
        lance:           Open ``LanceStore`` for ANN.
        embed_fn:        Function turning the query string into a dense
                         vector matching ``lance.dim``. Sync; called once
                         per query.
        top_k:           Number of fused results to return.
        candidate_k:     How many to pull from each source before fusion.
                         Larger = better recall, smaller = faster. Default
                         20 is enough to make RRF interesting without being
                         wasteful for our typical KB sizes.
        namespace:       Optional filter applied to both sources.
        classification:  Optional filter applied to both sources.
        vector_weight:   Multiplier on the ANN-side RRF contribution.
                         Default from spec §156.
        keyword_weight:  Multiplier on the FTS5-side RRF contribution.
                         Default from spec §156.

    Returns:
        Up to ``top_k`` :class:`Hit` instances, sorted by weighted RRF score
        descending. Empty list if both sources return nothing.
    """
    q = (query or "").strip()
    if not q:
        return []

    # ── FTS5 (keyword) path ──────────────────────────────────────────
    fts_hits = sqlite.fts_search(
        _safe_fts_query(q),
        top_k=candidate_k,
        namespace=namespace,
        classification=classification,
        exclude_superseded=exclude_superseded,
    )

    # ── Vector (ANN) path ────────────────────────────────────────────
    query_vec = embed_fn(q)
    # Fetch extra candidates to absorb any superseded chunks we'll drop.
    ann_top_k = candidate_k * 2 if exclude_superseded else candidate_k
    ann_hits = lance.ann_search(
        query_vec,
        top_k=ann_top_k,
        namespace=namespace,
        classification=classification,
    )
    if exclude_superseded and ann_hits:
        superseded = sqlite.get_superseded_chunk_ids([h.chunk_id for h in ann_hits])
        if superseded:
            ann_hits = [h for h in ann_hits if h.chunk_id not in superseded]

    # ── Weighted Reciprocal Rank Fusion ──────────────────────────────
    rrf_scores: dict[str, float] = {}
    rank_vector: dict[str, int] = {}
    rank_fts: dict[str, int] = {}

    for rank, ann in enumerate(ann_hits, start=1):
        # ANN row keys on chunk_id (LanceDB has both vector_id & chunk_id;
        # SqliteStore.fts_search yields chunk_id; align on chunk_id).
        rrf_scores[ann.chunk_id] = rrf_scores.get(ann.chunk_id, 0.0) + vector_weight / (
            RRF_K + rank
        )
        rank_vector[ann.chunk_id] = rank

    for rank, fts in enumerate(fts_hits, start=1):
        rrf_scores[fts.chunk_id] = rrf_scores.get(fts.chunk_id, 0.0) + keyword_weight / (
            RRF_K + rank
        )
        rank_fts[fts.chunk_id] = rank

    if not rrf_scores:
        return []

    # Hydrate all candidate chunks for tie-breaker fields.
    candidate_ids = list(rrf_scores.keys())
    rows_by_chunk = _fetch_chunk_rows(sqlite, candidate_ids)

    # Batch-fetch source_authority for all candidate documents.
    candidate_doc_ids = list(
        {str(rows_by_chunk[cid]["document_id"]) for cid in candidate_ids if cid in rows_by_chunk}
    )
    source_authorities = sqlite.get_source_authorities(candidate_doc_ids)

    def _sort_key(cid: str) -> tuple[float, int, str]:
        score = rrf_scores[cid]
        row = rows_by_chunk.get(cid) or {}
        doc_id = str(row.get("document_id", ""))
        authority = source_authorities.get(doc_id, "internal")
        authority_rank = _AUTHORITY_RANK.get(authority, 1)
        # Newer valid_from wins ties within the same authority tier.
        vf: str = row.get("valid_from") or ""
        return (score, authority_rank, vf)

    ordered_ids = sorted(candidate_ids, key=_sort_key, reverse=True)[:top_k]

    # Check which source documents carry open (unresolved) conflicts.
    hit_doc_ids = [
        str(rows_by_chunk[cid]["document_id"]) for cid in ordered_ids if cid in rows_by_chunk
    ]
    docs_with_conflicts = sqlite.get_docs_with_open_conflicts(hit_doc_ids)

    out: list[Hit] = []
    for cid in ordered_ids:
        row = rows_by_chunk.get(cid)
        if row is None:
            # Defensive: a chunk that's in FTS or ANN but not in
            # kb_chunks would mean a bug elsewhere; skip rather than
            # raise so partial degradation > complete failure.
            continue
        content = row.get("content")
        doc_id = str(row["document_id"])
        out.append(
            Hit(
                chunk_id=cid,
                score=rrf_scores[cid],
                rank_vector=rank_vector.get(cid),
                rank_fts=rank_fts.get(cid),
                document_id=doc_id,
                namespace=str(row["namespace"]),
                content=str(content) if content is not None else None,
                valid_from=row.get("valid_from"),
                has_open_conflicts=doc_id in docs_with_conflicts,
                source_authority=source_authorities.get(doc_id),
            )
        )
    return out


def _fetch_chunk_rows(sqlite: SqliteStore, chunk_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Look up chunk rows by chunk_id (SqliteStore exposes vector_id lookup;
    here we need chunk_id, so fall through to ``get_chunk`` per-row).

    Sized for our top_k (≤ 5) so the loop is cheap. Refactor to a single
    IN-clause query if top_k grows.
    """
    out: dict[str, dict[str, Any]] = {}
    for cid in chunk_ids:
        row = sqlite.get_chunk(cid)
        if row is not None:
            out[cid] = row
    return out
