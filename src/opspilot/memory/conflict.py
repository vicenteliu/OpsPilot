"""When a Memory entry and the KB disagree (ADR-0031, revised by ADR-0035).

Detected **when an answer is composed**, not when the entry is written. The
timing is the decision: at write time the human is present and has just confirmed
the entry, so a prompt then gets dismissed — they said two seconds ago that it
was right. The moment worth interrupting is months later, a different person, an
unrelated investigation, when the assistant holds both the recorded constraint
and a document that says the opposite. **That is the moment nobody knows both
statements exist.**

What is reused from the KB's machinery is the *record types* — a Conflict is
detected and left **open**, a human settles it with a **Resolution** — not the
detector. The KB's own path is cosine similarity between chunks at ingest and is
untouched.

The outcomes differ, because the KB's four are written for two Chunks:

* ``entry_superseded`` — the document is right; the constraint gets replaced by
  appending a new one (never edited: "we recorded it wrong" and "the world
  changed" have to stay distinguishable).
* ``chunk_superseded`` — the constraint is right; the document is stale or
  describes intended rather than actual behaviour. ADR-0029 already expects this
  to be the common answer when a verified local finding meets vendor
  documentation.
* ``dismissed`` — they only appeared to disagree.

``merged`` is unavailable: merging would mean editing the entry in place.
"""

from __future__ import annotations

import functools
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from ..dblock import lock_for
from ..timeutil import now_rfc3339

Resolution = Literal["entry_superseded", "chunk_superseded", "dismissed"]
RESOLUTIONS: Final[tuple[str, ...]] = ("entry_superseded", "chunk_superseded", "dismissed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_conflicts (
  id              TEXT PRIMARY KEY
                      CHECK (id GLOB 'mcf_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  memory_id       TEXT NOT NULL REFERENCES memory_entries(id),
  -- No foreign key to kb_chunks on purpose: a re-ingest regenerates chunk ids,
  -- and a conflict that vanishes because a document was re-ingested would take
  -- the disagreement with it.
  chunk_id        TEXT NOT NULL,
  note            TEXT NOT NULL,
  detected_in     TEXT,
  detected_at     TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','entry_superseded','chunk_superseded','dismissed')),
  resolved_by     TEXT,
  resolved_at     TEXT,
  resolution_note TEXT
);
-- One open conflict per pair. The same answer is composed many times, and a
-- fresh row on every turn would bury the one somebody has to settle.
CREATE UNIQUE INDEX IF NOT EXISTS idx_mcf_open_pair
  ON memory_conflicts(memory_id, chunk_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_mcf_status ON memory_conflicts(status, detected_at DESC);
"""

_COLS: Final[tuple[str, ...]] = (
    "id",
    "memory_id",
    "chunk_id",
    "note",
    "detected_in",
    "detected_at",
    "status",
    "resolved_by",
    "resolved_at",
    "resolution_note",
)


@dataclass(frozen=True, slots=True)
class MemoryConflict:
    id: str
    memory_id: str
    chunk_id: str
    note: str
    detected_in: str | None
    detected_at: str
    status: str = "open"
    resolved_by: str | None = None
    resolved_at: str | None = None
    resolution_note: str | None = None

    @property
    def is_open(self) -> bool:
        return self.status == "open"


def _serialised[M: Callable[..., Any]](method: M) -> M:
    """Hold the connection's lock for the whole method (see :mod:`opspilot.dblock`)."""

    @functools.wraps(method)
    def wrapper(self: MemoryConflictStore, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(M, wrapper)


def _row(r: tuple[Any, ...]) -> MemoryConflict:
    return MemoryConflict(**dict(zip(_COLS, tuple(r), strict=True)))


class MemoryConflictStore:
    """Open and settle disagreements between a Memory entry and a KB chunk."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = lock_for(conn)
        with self._lock:
            conn.executescript(_SCHEMA)
            conn.commit()

    @_serialised
    def open_conflict(
        self, *, memory_id: str, chunk_id: str, note: str, detected_in: str | None = None
    ) -> MemoryConflict:
        """Record that these two disagree. Idempotent while one is still open.

        Detecting is not settling. The row is opened by whoever noticed —
        including the assistant mid-answer — and stays open until a human decides
        which side loses, which is the same division the KB's own Conflicts use.
        """
        note = note.strip()
        if not note:
            raise ValueError("note is required: a conflict nobody can read is not actionable")
        existing = self._open_for(memory_id, chunk_id)
        if existing is not None:
            return existing
        conflict = MemoryConflict(
            id="mcf_" + secrets.token_hex(4),
            memory_id=memory_id,
            chunk_id=chunk_id,
            note=note,
            detected_in=detected_in,
            detected_at=now_rfc3339(),
        )
        self._conn.execute(
            "INSERT INTO memory_conflicts (id, memory_id, chunk_id, note, detected_in, detected_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                conflict.id,
                conflict.memory_id,
                conflict.chunk_id,
                conflict.note,
                conflict.detected_in,
                conflict.detected_at,
            ),
        )
        self._conn.commit()
        return conflict

    @_serialised
    def resolve(
        self, conflict_id: str, *, resolution: Resolution, resolved_by: str, note: str = ""
    ) -> None:
        """Settle it. ``resolved_by`` comes from the caller's identity.

        The reason is stored because six months on it is the only way to tell a
        real finding from a misdiagnosis someone enshrined — ADR-0029's argument,
        which is what this whole mechanism serves.
        """
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {RESOLUTIONS}, not {resolution!r}")
        if not resolved_by.strip():
            raise ValueError("resolved_by is required and comes from the caller's identity")
        cur = self._conn.execute(
            "UPDATE memory_conflicts SET status = ?, resolved_by = ?, resolved_at = ?, "
            "resolution_note = ? WHERE id = ? AND status = 'open'",
            (resolution, resolved_by, now_rfc3339(), note.strip() or None, conflict_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"memory conflict {conflict_id!r} not found or already settled")
        self._conn.commit()

    @_serialised
    def list_conflicts(
        self, *, status: str | None = "open", limit: int = 100
    ) -> list[MemoryConflict]:
        sql = "SELECT " + ", ".join(_COLS) + " FROM memory_conflicts"  # noqa: S608
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY detected_at DESC LIMIT ?"
        return [_row(r) for r in self._conn.execute(sql, (*params, limit)).fetchall()]

    @_serialised
    def count_open(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM memory_conflicts WHERE status = 'open'")
        return int(cur.fetchone()[0])

    def _open_for(self, memory_id: str, chunk_id: str) -> MemoryConflict | None:
        cur = self._conn.execute(
            "SELECT " + ", ".join(_COLS) + " FROM memory_conflicts "  # noqa: S608
            "WHERE memory_id = ? AND chunk_id = ? AND status = 'open'",
            (memory_id, chunk_id),
        )
        row = cur.fetchone()
        return _row(row) if row else None
