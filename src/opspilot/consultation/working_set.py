"""Working set — the problem an operator is currently chasing (ADR-0032).

Carried across a chain of one person's **Consultations** and expiring when the
problem does. Per-user by construction, because a Consultation is — which is why
it is **not part of Memory**: Memory is team-global and standing, a Working set is
one person's short-lived focus. Calling both "short-term memory" is how one word
came to cover three concepts (ADR-0035).

It carries the turn's **anchors**. Without one, a chat turn sees only the global
Memory entries, because nothing tells it which site or device it is about.

Opened and closed by hand, with an **unconditional inactivity fallback** that
closes it anyway — nobody returns to press "close" at the moment a problem is
solved, and a Working set that never expires quietly injects the wrong context
into every later conversation without ever raising an error.

**The fallback announces itself.** A set that expired silently leaves the operator
misreading why the assistant lost the thread, so the closure is held until it has
been told to its owner, once.
"""

from __future__ import annotations

import functools
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal, cast

from ..dblock import lock_for
from ..timeutil import now_rfc3339

# Days of silence before the fallback closes a set. A Working set tracks one
# investigation, not a quarter: long enough to survive a weekend and a week of
# other work, short enough that a solved problem stops steering answers.
IDLE_DAYS: Final[int] = 14

CloseReason = Literal["manual", "inactivity"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS working_sets (
  id             TEXT PRIMARY KEY
                     CHECK (id GLOB 'ws_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  owner          TEXT NOT NULL CHECK (length(owner) >= 1),
  title          TEXT NOT NULL CHECK (length(title) >= 1),
  scope          TEXT,
  asset_id       TEXT,
  opened_at      TEXT NOT NULL,
  last_active_at TEXT NOT NULL,
  closed_at      TEXT,
  closed_reason  TEXT CHECK (closed_reason IN ('manual','inactivity')),
  announced_at   TEXT
);
-- One open set per person: "the problem you are chasing" is singular by
-- definition, and two would put back the question of which one anchors a turn.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ws_one_open
  ON working_sets(owner) WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_ws_sweep ON working_sets(closed_at, last_active_at);
"""

_COLS: Final[tuple[str, ...]] = (
    "id",
    "owner",
    "title",
    "scope",
    "asset_id",
    "opened_at",
    "last_active_at",
    "closed_at",
    "closed_reason",
    "announced_at",
)


@dataclass(frozen=True, slots=True)
class WorkingSet:
    id: str
    owner: str
    title: str
    scope: str | None
    asset_id: str | None
    opened_at: str
    last_active_at: str
    closed_at: str | None = None
    closed_reason: str | None = None
    announced_at: str | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def needs_announcing(self) -> bool:
        """Closed by the fallback and not yet told to its owner."""
        return self.closed_reason == "inactivity" and self.announced_at is None

    def announcement(self) -> str:
        """What the owner is told, once, in their next Consultation."""
        return (
            f'Your working set "{self.title}" was closed after {IDLE_DAYS} days without '
            f"activity, so this conversation no longer carries its context. Reopen it if "
            f"you are still on that problem."
        )


def _serialised[M: Callable[..., Any]](method: M) -> M:
    """Hold the connection's lock for the whole method (see :mod:`opspilot.dblock`)."""

    @functools.wraps(method)
    def wrapper(self: WorkingSetStore, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(M, wrapper)


def _row(r: tuple[Any, ...]) -> WorkingSet:
    return WorkingSet(**dict(zip(_COLS, tuple(r), strict=True)))


class WorkingSetStore:
    """One open Working set per person, with the fallback that closes it."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = lock_for(conn)
        with self._lock:
            conn.executescript(_SCHEMA)
            conn.commit()

    @_serialised
    def open(
        self,
        *,
        owner: str,
        title: str,
        scope: str | None = None,
        asset_id: str | None = None,
    ) -> WorkingSet:
        """Start chasing a problem. Any set already open for *owner* is closed.

        Closing the previous one counts as **manual**: the person deliberately
        switched, so there is nothing to announce back to them.
        """
        owner, title = owner.strip(), title.strip()
        if not owner:
            raise ValueError("owner is required and comes from the caller's identity")
        if not title:
            raise ValueError("title is required: a working set nobody can name is not one")
        current = self._current(owner)
        if current is not None:
            self._close(current.id, reason="manual")
        now = now_rfc3339()
        ws = WorkingSet(
            id="ws_" + secrets.token_hex(4),
            owner=owner,
            title=title,
            scope=(scope.strip() or None) if scope else None,
            asset_id=asset_id or None,
            opened_at=now,
            last_active_at=now,
        )
        self._conn.execute(
            "INSERT INTO working_sets (id, owner, title, scope, asset_id, opened_at, last_active_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (ws.id, ws.owner, ws.title, ws.scope, ws.asset_id, ws.opened_at, ws.last_active_at),
        )
        self._conn.commit()
        return ws

    @_serialised
    def current(self, owner: str) -> WorkingSet | None:
        """The open set for *owner*, or ``None``."""
        return self._current(owner)

    @_serialised
    def touch(self, owner: str) -> None:
        """Mark activity, so the fallback measures silence rather than age."""
        self._conn.execute(
            "UPDATE working_sets SET last_active_at = ? WHERE owner = ? AND closed_at IS NULL",
            (now_rfc3339(), owner),
        )
        self._conn.commit()

    @_serialised
    def close(self, working_set_id: str, *, reason: CloseReason = "manual") -> None:
        self._close(working_set_id, reason=reason)
        self._conn.commit()

    @_serialised
    def sweep(self, *, idle_days: int = IDLE_DAYS, now: str | None = None) -> list[WorkingSet]:
        """Close every set idle past the window. Returns what it closed.

        Unconditional on purpose: the close action is the one nobody performs,
        because the moment a problem is solved is the moment you move on.
        """
        stamp = now or now_rfc3339()
        cutoff = (
            datetime.fromisoformat(stamp.replace("Z", "+00:00")) - timedelta(days=idle_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = self._conn.execute(
            "SELECT " + ", ".join(_COLS) + " FROM working_sets "  # noqa: S608
            "WHERE closed_at IS NULL AND last_active_at < ?",
            (cutoff,),
        )
        stale = [_row(r) for r in cur.fetchall()]
        for ws in stale:
            self._conn.execute(
                "UPDATE working_sets SET closed_at = ?, closed_reason = 'inactivity' WHERE id = ?",
                (stamp, ws.id),
            )
        if stale:
            self._conn.commit()
        return [_row_closed(ws, stamp) for ws in stale]

    @_serialised
    def take_announcement(self, owner: str) -> str | None:
        """Return the pending closure notice for *owner*, once, then mark it told.

        Called when a Consultation opens. A set that expired silently leaves the
        operator misreading why the assistant lost the thread, so this is the one
        thing the fallback owes them.
        """
        cur = self._conn.execute(
            "SELECT " + ", ".join(_COLS) + " FROM working_sets "  # noqa: S608
            "WHERE owner = ? AND closed_reason = 'inactivity' AND announced_at IS NULL "
            "ORDER BY closed_at DESC LIMIT 1",
            (owner,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        ws = _row(row)
        self._conn.execute(
            "UPDATE working_sets SET announced_at = ? WHERE id = ?", (now_rfc3339(), ws.id)
        )
        self._conn.commit()
        return ws.announcement()

    @_serialised
    def get(self, working_set_id: str) -> WorkingSet | None:
        cur = self._conn.execute(
            "SELECT " + ", ".join(_COLS) + " FROM working_sets WHERE id = ?",  # noqa: S608
            (working_set_id,),
        )
        row = cur.fetchone()
        return _row(row) if row else None

    @_serialised
    def history(self, owner: str, *, limit: int = 20) -> list[WorkingSet]:
        cur = self._conn.execute(
            "SELECT " + ", ".join(_COLS) + " FROM working_sets WHERE owner = ? "  # noqa: S608
            "ORDER BY opened_at DESC LIMIT ?",
            (owner, limit),
        )
        return [_row(r) for r in cur.fetchall()]

    # ── internals (already under the lock) ───────────────────────────

    def _current(self, owner: str) -> WorkingSet | None:
        cur = self._conn.execute(
            "SELECT " + ", ".join(_COLS) + " FROM working_sets "  # noqa: S608
            "WHERE owner = ? AND closed_at IS NULL",
            (owner,),
        )
        row = cur.fetchone()
        return _row(row) if row else None

    def _close(self, working_set_id: str, *, reason: CloseReason) -> None:
        cur = self._conn.execute(
            "UPDATE working_sets SET closed_at = ?, closed_reason = ? "
            "WHERE id = ? AND closed_at IS NULL",
            (now_rfc3339(), reason, working_set_id),
        )
        if cur.rowcount == 0:
            cur2 = self._conn.execute("SELECT 1 FROM working_sets WHERE id = ?", (working_set_id,))
            if cur2.fetchone() is None:
                raise KeyError(f"working set {working_set_id!r} not found")


def _row_closed(ws: WorkingSet, stamp: str) -> WorkingSet:
    """The post-sweep view of a set the sweep just closed."""
    return WorkingSet(
        **{**{k: getattr(ws, k) for k in _COLS}, "closed_at": stamp, "closed_reason": "inactivity"}
    )
