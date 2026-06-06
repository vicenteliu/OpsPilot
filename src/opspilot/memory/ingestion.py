"""End-to-end KB ingestion pipeline.

Per-file flow:

    discover  → markitdown  → redact → chunk → embed → upsert
                (.md passes through unchanged)

* **discover**  — caller supplies a path or list of paths; we walk dirs
  ourselves (skipping hidden files) so a single CLI call can ingest a
  whole directory recursively.
* **markitdown** — :func:`markitdown_adapter.to_markdown` returns the
  markdown body and the detected source type. Vision OFF.
* **redact**   — :class:`opspilot.redaction.Redactor`; we hard-fail if
  any redaction *hit* has a placeholder type in
  :data:`HARD_FAIL_PLACEHOLDER_TYPES` (private keys, etc.) — these are
  things that should never reach a KB even with the placeholder swap.
* **chunk**    — :func:`memory.chunker.chunk_markdown` (PR-2 default).
* **embed**    — caller-injected ``embed_fn`` (matches retrieval's API);
  no provider import.
* **upsert**   — SQLite ``kb_documents`` + ``kb_chunks`` (PR-4) and
  LanceDB vectors. Restricted classification skips the vector path
  (FTS-only retrieval).

Dedup: ``content_hash`` (sha256 of the redacted markdown) is the anchor.
A second ingest of the same path with unchanged content is a no-op; if
content changed we delete old chunks (FK cascade) and re-write.

Audit: every run writes one row to ``ingest_runs`` with totals. PR-6+
will add a more granular audit_log row per document.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Final

from ..errors import OpsPilotError
from ..ids import new_ulid_id
from ..observability import record_ingest
from ..redaction import Redactor
from ..timeutil import now_rfc3339
from .chunker import Chunk, ChunkConfig, chunk_markdown
from .conflict import detect_and_store_conflicts
from .lance_store import LanceStore, VectorRecord
from .markitdown_adapter import AdapterError, AdapterResult, to_markdown
from .sqlite_store import SqliteStore

EmbedFn = Callable[[str], list[float]]


# Placeholder types from session/templates/redaction-rules.template.yaml.
# Even after the rule rewrote them to a placeholder, we refuse to ingest
# any text where these matched at all — the original is unrecoverable
# from the placeholder, but we don't want such content cached anywhere
# downstream (KB consumers re-render content; private keys / cloud
# secrets must never reach persistent storage in any form).
HARD_FAIL_PLACEHOLDER_TYPES: Final[frozenset[str]] = frozenset(
    {"private_key", "aws_secret", "aws_akid", "secret"}
)


class IngestionError(OpsPilotError):
    """Raised when an ingest cannot proceed (PII hit / unsupported file)."""


# ── Public dataclasses ────────────────────────────────────────────────


@dataclass(frozen=True)
class IngestConfig:
    """Defaults for one ingestion run.

    Most callers will pass this from their kb-config.yaml; CLI also
    overrides individual fields per-invocation.
    """

    kb_id: str = "opspilot:public-kb"
    namespace: str | None = None  # None → use kb_id as namespace
    classification: str = "internal"
    embedding_model: str = "ollama-local/nomic-embed-text-v2-moe@2026-04"
    embedding_dim: int = 768
    chunk_strategy: str = "headings_then_size"
    redaction_rules_version: str = "1.0.0"
    chunk_config: ChunkConfig = field(default_factory=ChunkConfig)
    detect_conflicts: bool = True  # run conflict detection after each doc
    source_authority: str = "internal"  # official | vendor | internal | unverified
    conflict_similarity_threshold: float = 0.82


@dataclass
class FileResult:
    """One source file's outcome."""

    source_path: Path
    document_id: str | None
    chunks_written: int
    chunks_skipped_unchanged: bool
    redaction_hits: int
    error: str | None = None


@dataclass
class IngestStats:
    """Aggregate of an ingestion run."""

    run_id: str
    started_at: str
    finished_at: str
    docs_total: int
    docs_succeeded: int
    docs_failed: int
    chunks_total: int
    redaction_hits: int
    duration_ms: int
    files: list[FileResult] = field(default_factory=list)


# ── Discovery ─────────────────────────────────────────────────────────


def discover_files(paths: Iterable[Path]) -> list[Path]:
    """Walk inputs to a flat list of files.

    Hidden files / dirs (starting with ``.``) are skipped — they're
    almost always editor swap files or VCS metadata.
    """
    out: list[Path] = []
    for p in paths:
        if p.is_file():
            if not p.name.startswith("."):
                out.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not any(part.startswith(".") for part in f.parts):
                    out.append(f)
    return out


# ── Pipeline ──────────────────────────────────────────────────────────


def ingest(
    paths: Iterable[Path],
    *,
    sqlite: SqliteStore,
    lance: LanceStore,
    redactor: Redactor,
    embed_fn: EmbedFn,
    config: IngestConfig | None = None,
) -> IngestStats:
    """Run the full pipeline over ``paths``. Returns aggregate stats.

    Per-file failures are recorded in :class:`FileResult` (``error``
    field) and counted in ``docs_failed``; the run itself does NOT raise
    so a partial failure doesn't sink the rest of the batch. The single
    exception is :class:`IngestionError` for hard-fail PII — that
    halts the whole run so the operator must intervene.
    """
    cfg = config or IngestConfig()
    namespace = cfg.namespace or cfg.kb_id

    started_at = now_rfc3339()
    started_perf = time.perf_counter()
    run_id = new_ulid_id("run")

    files = discover_files(paths)
    file_results: list[FileResult] = []
    chunks_total = 0
    redaction_hits_total = 0
    succeeded = 0
    failed = 0

    for path in files:
        try:
            r = _ingest_one(
                path,
                sqlite=sqlite,
                lance=lance,
                redactor=redactor,
                embed_fn=embed_fn,
                namespace=namespace,
                cfg=cfg,
            )
            file_results.append(r)
            chunks_total += r.chunks_written
            redaction_hits_total += r.redaction_hits
            if r.error:
                failed += 1
            else:
                succeeded += 1
        except IngestionError:
            # Hard PII fail — stop the whole run so the operator notices.
            raise
        except (AdapterError, Exception) as e:  # noqa: BLE001
            file_results.append(
                FileResult(
                    source_path=path,
                    document_id=None,
                    chunks_written=0,
                    chunks_skipped_unchanged=False,
                    redaction_hits=0,
                    error=f"{type(e).__name__}: {e}",
                )
            )
            failed += 1

    finished_at = now_rfc3339()
    duration_ms = int((time.perf_counter() - started_perf) * 1000)

    _write_ingest_run_row(
        sqlite,
        run_id=run_id,
        kb_id=cfg.kb_id,
        started_at=started_at,
        finished_at=finished_at,
        docs_total=len(files),
        docs_succeeded=succeeded,
        docs_failed=failed,
        chunks_total=chunks_total,
        redaction_hits=redaction_hits_total,
    )

    record_ingest(succeeded=succeeded, failed=failed)

    return IngestStats(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        docs_total=len(files),
        docs_succeeded=succeeded,
        docs_failed=failed,
        chunks_total=chunks_total,
        redaction_hits=redaction_hits_total,
        duration_ms=duration_ms,
        files=file_results,
    )


# ── Single-file step ──────────────────────────────────────────────────


def _ingest_one(
    path: Path,
    *,
    sqlite: SqliteStore,
    lance: LanceStore,
    redactor: Redactor,
    embed_fn: EmbedFn,
    namespace: str,
    cfg: IngestConfig,
) -> FileResult:
    # 1. Convert to markdown (or pass through if already .md).
    adapter_out: AdapterResult = to_markdown(path)
    raw_md = adapter_out.markdown

    # 2. Redact + hard-fail on disallowed placeholder types.
    red = redactor.redact(raw_md)
    redaction_hits = red.hit_count
    bad = red.types_seen() & HARD_FAIL_PLACEHOLDER_TYPES
    if bad:
        raise IngestionError(
            f"hard-fail PII in {path}: redaction matched {sorted(bad)}; refusing to ingest"
        )
    md = red.text

    # 3. Compute content hash (post-redaction so dedup is on the form
    #    that actually reaches storage).
    digest = hashlib.sha256(md.encode("utf-8")).hexdigest()
    content_hash = f"sha256:{digest}"
    doc_id = f"doc_{digest[:8]}"

    # Dedup: identical content + identical source_path = no-op.
    existing = _find_doc_by_source_path(sqlite, str(path))
    if existing and existing[1] == content_hash:
        return FileResult(
            source_path=path,
            document_id=existing[0],
            chunks_written=0,
            chunks_skipped_unchanged=True,
            redaction_hits=redaction_hits,
        )

    # If content changed, delete old doc + chunks first (FK cascade
    # cleans chunks).
    if existing:
        _delete_doc_with_vectors(sqlite, lance, existing[0])

    # 4. Chunk.
    chunks: list[Chunk] = chunk_markdown(md, config=cfg.chunk_config)
    if not chunks:
        # An adapter producing zero chunks is suspicious — empty doc
        # would crash kb_search anyway. Treat as an error.
        return FileResult(
            source_path=path,
            document_id=None,
            chunks_written=0,
            chunks_skipped_unchanged=False,
            redaction_hits=redaction_hits,
            error=f"chunker produced zero chunks for {path}",
        )

    # 5. Embed + upsert.
    title = adapter_out.title or path.stem
    valid_from = _extract_valid_from(path, md)
    sqlite.upsert_document(
        {
            "id": doc_id,
            "source_path": str(path),
            "title": title,
            "classification": cfg.classification,
            "content_hash": content_hash,
            "ingested_at": now_rfc3339(),
            "language": _detect_language(md),
            "tags": [],
            "namespace": namespace,
            "chunk_strategy": cfg.chunk_strategy,
            "chunk_count": len(chunks),
            "embedding_model": cfg.embedding_model,
            "embedding_dim": cfg.embedding_dim,
            "redaction_passed": True,
            "redaction_rules_version": cfg.redaction_rules_version,
            "valid_from": valid_from,
            "source_authority": cfg.source_authority,
        }
    )

    chunk_rows: list[dict[str, object]] = []
    vector_records: list[VectorRecord] = []

    for seq, chunk in enumerate(chunks):
        chunk_digest = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        chunk_id = f"chk_{chunk_digest[:8]}"
        vector_id = f"vec_{chunk_id}"

        chunk_rows.append(
            {
                "id": chunk_id,
                "document_id": doc_id,
                "seq": seq,
                "content": chunk.content,
                "content_hash": f"sha256:{chunk_digest}",
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "heading_path": list(chunk.heading_path),
                "anchor": chunk.anchor,
                "token_count": chunk.token_count,
                "embedding_model": cfg.embedding_model,
                "vector_id": vector_id,
                "valid_from": valid_from,
                "metadata": {
                    "tags": [],
                    "namespace": namespace,
                    "classification": cfg.classification,
                    "language": _detect_language(chunk.content),
                },
            }
        )

        # D7: classification=restricted skips vector path entirely (FTS only).
        if cfg.classification != "restricted":
            vec = embed_fn(chunk.content)
            vector_records.append(
                VectorRecord(
                    vector_id=vector_id,
                    embedding=vec,
                    document_id=doc_id,
                    chunk_id=chunk_id,
                    namespace=namespace,
                    classification=cfg.classification,
                    language=_detect_language(chunk.content),
                    tags=[],
                    embedding_model=cfg.embedding_model,
                )
            )

    sqlite.upsert_chunks(chunk_rows)
    if vector_records:
        lance.upsert_vectors(vector_records)

    # 6. Conflict detection (skip restricted docs — no vectors to compare).
    if cfg.detect_conflicts and cfg.classification != "restricted" and vector_records:
        detect_and_store_conflicts(
            new_doc_id=doc_id,
            new_chunks=chunk_rows,
            lance=lance,
            sqlite=sqlite,
            embed_fn=embed_fn,
            similarity_threshold=cfg.conflict_similarity_threshold,
        )

    return FileResult(
        source_path=path,
        document_id=doc_id,
        chunks_written=len(chunks),
        chunks_skipped_unchanged=False,
        redaction_hits=redaction_hits,
    )


# ── Helpers ───────────────────────────────────────────────────────────


def _find_doc_by_source_path(sqlite: SqliteStore, source_path: str) -> tuple[str, str] | None:
    """Returns ``(doc_id, content_hash)`` or None.

    ``idx_doc_source_path`` makes this O(log n).
    """
    cur = sqlite._conn.execute(  # noqa: SLF001 — SqliteStore lacks a public lookup
        "SELECT id, content_hash FROM kb_documents WHERE source_path = ?",
        (source_path,),
    )
    r = cur.fetchone()
    if r is None:
        return None
    return (str(r["id"]), str(r["content_hash"]))


def _delete_doc_with_vectors(sqlite: SqliteStore, lance: LanceStore, doc_id: str) -> None:
    """Remove a doc and its chunks from both stores.

    SQLite handles ``kb_chunks`` via FK cascade; we have to fetch
    ``vector_id``s before the delete so we can also clear LanceDB.
    """
    cur = sqlite._conn.execute(  # noqa: SLF001
        "SELECT vector_id FROM kb_chunks WHERE document_id = ?", (doc_id,)
    )
    vector_ids = [r["vector_id"] for r in cur.fetchall()]
    sqlite._conn.execute(  # noqa: SLF001
        "DELETE FROM kb_documents WHERE id = ?", (doc_id,)
    )
    sqlite._conn.commit()
    if vector_ids:
        lance.delete_by_vector_ids(vector_ids)


def _write_ingest_run_row(
    sqlite: SqliteStore,
    *,
    run_id: str,
    kb_id: str,
    started_at: str,
    finished_at: str,
    docs_total: int,
    docs_succeeded: int,
    docs_failed: int,
    chunks_total: int,
    redaction_hits: int,
) -> None:
    status = "succeeded" if docs_failed == 0 else "failed"
    sqlite._conn.execute(  # noqa: SLF001
        """
        INSERT INTO ingest_runs (
          id, kb_id, started_at, finished_at, status,
          docs_total, docs_succeeded, docs_failed,
          chunks_total, tokens_embedded, cost_usd,
          redaction_hits, redaction_hard_fails
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0.0, ?, 0)
        """,
        (
            run_id,
            kb_id,
            started_at,
            finished_at,
            status,
            docs_total,
            docs_succeeded,
            docs_failed,
            chunks_total,
            redaction_hits,
        ),
    )
    sqlite._conn.commit()


def _detect_language(text: str) -> str:
    """Quick-and-dirty CJK vs latin heuristic.

    Good enough for KB metadata; PR-7+ may swap in a proper detector.
    """
    if any("一" <= ch <= "鿿" for ch in text):
        return "zh-CN"
    return "en"


def _normalize_date(val: str) -> str:
    """Coerce a freeform date string to ``YYYY-MM-DDTHH:MM:SSZ``."""
    val = val.strip()
    # ISO datetime must be checked first — date-only formats use val[:10]
    # which would otherwise strip the time component.
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", val)
    if m:
        return m.group(1) + "Z"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(val[:10], fmt).strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            pass
    return val


def _extract_valid_from(path: Path, markdown: str) -> str:
    """Return ISO8601 effective date for the document.

    Priority: YAML frontmatter → filename date pattern → file mtime → now.
    """
    # 1. YAML frontmatter (--- ... ---)
    if markdown.startswith("---"):
        end = markdown.find("\n---", 3)
        if end > 0:
            try:
                import yaml  # noqa: PLC0415

                fm = yaml.safe_load(markdown[3:end])
                if isinstance(fm, dict):
                    for key in ("date", "valid_from", "updated", "last_updated", "created"):
                        val = fm.get(key)
                        if val:
                            return _normalize_date(str(val))
            except Exception:  # noqa: BLE001
                pass

    # 2. Filename date pattern YYYY[-_]MM[-_]DD
    m = re.search(r"(\d{4})[_-](\d{2})[_-](\d{2})", path.stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T00:00:00Z"

    # 3. File mtime
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        pass

    return now_rfc3339()
