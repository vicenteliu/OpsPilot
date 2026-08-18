"""Memory — the store for knowledge that has no table (ADR-0031, revised by ADR-0035).

OpsPilot's **second owned domain**, after Inventory. It holds standing facts
about the environment that no other table wants: constraints, gotchas, and
relationships an operator would otherwise carry in their head.

  "Do not restart the ESXi cluster on Tuesday evening, finance runs its batch."

The boundary is *shape*, not subject. If a thing's natural form is a set of
fields it belongs in a table; if it is one sentence, it belongs here. And the
rule that keeps the boundary honest runs the other way: **when entries pile up
until you want to query them by field, that is the signal to build a table — not
to give Memory fields.**

An entry is **admitted**, never harvested: a human writes it, or pins a sentence
from a Consultation, and supplies the reason in the same act (ADR-0030). The
actor comes from the caller's identity and never from the request.

A superseded entry is **appended, not overwritten**. A Memory entry is not a
projection of something else — it is the original — so "we recorded it wrong"
and "the world changed" have to stay distinguishable, and the superseded entry
keeps its review date so the history shows how long a constraint stayed true.
"""

from __future__ import annotations

import functools
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, cast

from ..dblock import lock_for
from ..timeutil import now_rfc3339

# Un-anchored entries are injected on every turn, so they are capped. The cap
# does not exist to save tokens; it exists to force the recognition that there
# should not be dozens of *global* constraints. On overflow the entry gains an
# anchor or an older one is archived — both are the right conversation to have.
GLOBAL_ENTRY_CAP = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entries (
  id                  TEXT PRIMARY KEY
                          CHECK (id GLOB 'mem_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  statement           TEXT NOT NULL CHECK (length(statement) BETWEEN 1 AND 500),
  reason              TEXT NOT NULL CHECK (length(reason) >= 1),
  actor               TEXT NOT NULL CHECK (length(actor) >= 1),
  created_at          TEXT NOT NULL,
  review_after        TEXT,
  asset_id            TEXT,
  scope               TEXT,
  source_ref          TEXT,
  superseded_by       TEXT REFERENCES memory_entries(id),
  superseded_at       TEXT,
  archived_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_mem_scope    ON memory_entries(scope);
CREATE INDEX IF NOT EXISTS idx_mem_asset    ON memory_entries(asset_id);
CREATE INDEX IF NOT EXISTS idx_mem_live     ON memory_entries(superseded_at, archived_at);
"""


class AdmissionError(Exception):
    """Raised when an entry cannot be admitted as asked.

    Named for the act, not the store: what fails here is always a human's
    attempt to admit something (ADR-0030) — a missing reason, a self-reported
    actor, one global constraint too many.
    """


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """One admitted fact: a sentence, a reason, who said it, and when.

    ``asset_id`` and ``scope`` are the two **anchors** — the address the sentence
    applies at. Both may be empty; empty on both is a *global* constraint.
    Exactly two exist and a third will not be added: an anchor is where a
    sentence applies, not a field about a thing, and wanting a third is evidence
    that what is wanted is a table.
    """

    id: str
    statement: str
    reason: str
    actor: str
    created_at: str
    review_after: str | None = None
    asset_id: str | None = None
    scope: str | None = None
    source_ref: str | None = None
    superseded_by: str | None = None
    superseded_at: str | None = None
    archived_at: str | None = None

    @property
    def is_global(self) -> bool:
        return not self.asset_id and not self.scope

    @property
    def is_live(self) -> bool:
        return self.superseded_at is None and self.archived_at is None

    def review_overdue_at(self, now: str) -> bool:
        """Past its review date — a *label*, never a reason to withhold it.

        Environment constraints rot silently: finance moves the batch to Thursday
        and nobody writes anything anywhere. Hard expiry was rejected because it
        drops a correct constraint at the worst possible moment; the entry stays
        available and carries "not reviewed since …" when it surfaces.
        """
        return self.review_after is not None and self.review_after < now


def _serialised[M: Callable[..., Any]](method: M) -> M:
    """Hold the connection's lock for the whole method (see :mod:`opspilot.dblock`)."""

    @functools.wraps(method)
    def wrapper(self: MemoryStore, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(M, wrapper)


# Explicit column order, so rows read the same whether or not the caller's
# connection sets ``row_factory`` (the shared KB connection does; a bare one does not).
_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "statement",
    "reason",
    "actor",
    "created_at",
    "review_after",
    "asset_id",
    "scope",
    "source_ref",
    "superseded_by",
    "superseded_at",
    "archived_at",
)
_SELECT: Final[str] = "SELECT " + ", ".join(_COLUMNS) + " FROM memory_entries"


def _row(r: tuple[Any, ...]) -> MemoryEntry:
    return MemoryEntry(**dict(zip(_COLUMNS, tuple(r), strict=True)))


class MemoryStore:
    """CRUD over ``memory_entries``, sharing the KB connection like Inventory."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = lock_for(conn)
        with self._lock:
            conn.executescript(_SCHEMA)
            conn.commit()

    # ── admission ────────────────────────────────────────────────────

    @_serialised
    def admit(
        self,
        *,
        statement: str,
        reason: str,
        actor: str,
        asset_id: str | None = None,
        scope: str | None = None,
        review_after: str | None = None,
        source_ref: str | None = None,
    ) -> MemoryEntry:
        """Record one admitted fact.

        ``actor`` is the caller's identity, supplied by the call site and never
        taken from a request body — the same rule as an Asset event, a Resolution
        and a Correction, and for the same reason: this is a decision about what
        the assistant will believe, so the one thing that must not be
        self-reported is who decided.

        ``reason`` is mandatory. Six months on it is the only way to tell a real
        finding from a misdiagnosis someone enshrined, which is exactly what the
        review date asks a reader to judge.
        """
        statement, reason, actor = statement.strip(), reason.strip(), actor.strip()
        if not statement:
            raise AdmissionError("statement is empty")
        if not reason:
            raise AdmissionError(
                "reason is required: an entry nobody can judge later is not admissible"
            )
        if not actor:
            raise AdmissionError("actor is required and comes from the caller's identity")

        if not asset_id and not scope and self._count_live_global() >= GLOBAL_ENTRY_CAP:
            raise AdmissionError(
                f"{GLOBAL_ENTRY_CAP} global entries already; give this one an anchor "
                "or archive one that no longer holds"
            )

        entry = MemoryEntry(
            id="mem_" + secrets.token_hex(4),
            statement=statement,
            reason=reason,
            actor=actor,
            created_at=now_rfc3339(),
            review_after=review_after,
            asset_id=asset_id or None,
            scope=(scope.strip() or None) if scope else None,
            source_ref=source_ref or None,
        )
        self._conn.execute(
            "INSERT INTO memory_entries (id, statement, reason, actor, created_at, "
            "review_after, asset_id, scope, source_ref) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                entry.id,
                entry.statement,
                entry.reason,
                entry.actor,
                entry.created_at,
                entry.review_after,
                entry.asset_id,
                entry.scope,
                entry.source_ref,
            ),
        )
        self._conn.commit()
        return entry

    @_serialised
    def supersede(
        self,
        entry_id: str,
        *,
        statement: str,
        reason: str,
        actor: str,
        review_after: str | None = None,
        source_ref: str | None = None,
    ) -> MemoryEntry:
        """Append a replacement and mark the old entry superseded.

        Never an in-place edit. The old entry keeps its own reason and review
        date, so the history answers "how long did this stay true" — the only
        data there is for judging how often constraints of that kind change.
        """
        old = self.get(entry_id)
        if old is None:
            raise KeyError(f"memory entry {entry_id!r} not found")
        if not old.is_live:
            raise AdmissionError(f"{entry_id} is already superseded or archived")
        new = self.admit(
            statement=statement,
            reason=reason,
            actor=actor,
            asset_id=old.asset_id,
            scope=old.scope,
            review_after=review_after,
            source_ref=source_ref,
        )
        self._conn.execute(
            "UPDATE memory_entries SET superseded_by = ?, superseded_at = ? WHERE id = ?",
            (new.id, now_rfc3339(), entry_id),
        )
        self._conn.commit()
        return new

    @_serialised
    def archive(self, entry_id: str) -> None:
        """Retire an entry without replacing it — it simply no longer holds."""
        cur = self._conn.execute(
            "UPDATE memory_entries SET archived_at = ? WHERE id = ? AND archived_at IS NULL",
            (now_rfc3339(), entry_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"memory entry {entry_id!r} not found or already archived")
        self._conn.commit()

    # ── reads ────────────────────────────────────────────────────────

    @_serialised
    def get(self, entry_id: str) -> MemoryEntry | None:
        cur = self._conn.execute(f"{_SELECT} WHERE id = ?", (entry_id,))
        row = cur.fetchone()
        return _row(row) if row is not None else None

    @_serialised
    def applicable(
        self, *, asset_id: str | None = None, scope: str | None = None
    ) -> list[MemoryEntry]:
        """Live entries that apply at this address, newest first.

        This is a **filter, not a ranking**. Memory does not join hybrid search:
        its retrieval condition is "does this constraint apply here", and a
        shared relevance ranking would erase the distinction that answer-time
        conflict detection against the KB depends on.

        Global entries (no anchor) always apply.
        """
        clauses = ["superseded_at IS NULL", "archived_at IS NULL"]
        params: list[Any] = []
        anchored = ["(asset_id IS NULL AND scope IS NULL)"]
        if asset_id:
            anchored.append("asset_id = ?")
            params.append(asset_id)
        if scope:
            anchored.append("scope = ?")
            params.append(scope)
        clauses.append("(" + " OR ".join(anchored) + ")")
        cur = self._conn.execute(
            f"{_SELECT} WHERE "  # noqa: S608 — clauses are static
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC",
            tuple(params),
        )
        return [_row(r) for r in cur.fetchall()]

    @_serialised
    def list_entries(self, *, include_retired: bool = False, limit: int = 200) -> list[MemoryEntry]:
        sql = _SELECT
        if not include_retired:
            sql += " WHERE superseded_at IS NULL AND archived_at IS NULL"
        sql += " ORDER BY created_at DESC LIMIT ?"
        return [_row(r) for r in self._conn.execute(sql, (limit,)).fetchall()]  # noqa: S608

    @_serialised
    def scopes(self) -> list[str]:
        """Every scope in use — the pick side of pick-or-create.

        Free text alone drifts: "HQ", "hq" and "head office" become three scopes
        and anchor-filtered retrieval silently misses. Offering what already
        exists lets the vocabulary converge without anyone inventing a taxonomy
        up front.
        """
        cur = self._conn.execute(
            "SELECT DISTINCT scope FROM memory_entries WHERE scope IS NOT NULL ORDER BY scope"
        )
        return [str(r[0]) for r in cur.fetchall()]

    def _count_live_global(self) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE asset_id IS NULL AND scope IS NULL "
            "AND superseded_at IS NULL AND archived_at IS NULL"
        )
        return int(cur.fetchone()[0])
