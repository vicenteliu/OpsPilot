"""Consultation — the conversational surface (ADR-0032).

A **Consultation** is a multi-turn conversation between a **User** and the
assistant: the surface where an operator actually works a problem, grounded in
the KB, Memory and Skills. It is deliberately weak. It reads, and the only thing
it may put forward is a **Memory entry** for the human present to admit. It
cannot emit a Proposed action and cannot be Distilled — to do either it is
*escalated* into a **Session**, carrying a Work item description and nothing
else, because a transcript is not freezable and a Fixture must be.

Two properties pay for calling it cheap:

**Private.** Visible to its author and to admins. A surface colleagues can browse
is one where people weigh their words, and a surface where people weigh their
words is a poor troubleshooting tool. Knowledge leaves by escalation or by an
admitted Memory entry — both team-visible, both through a human.

**Short-lived.** Cleaned up after :data:`RETENTION_DAYS`, because Consultations
collect pasted logs, configs and stack traces with none of the redaction a Work
item passes through on its way into a Session.

Unless they are **pinned**, which happens on exactly two events: escalation, and
being cited as the source of a Memory entry. Both leave a permanent record
pointing back here, and a permanent record aimed at something the system deletes
on a timer survives in name only.
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

RETENTION_DAYS: Final[int] = 90

PinReason = Literal["escalated", "memory_source"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS consultations (
  id            TEXT PRIMARY KEY
                    CHECK (id GLOB 'con_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  author        TEXT NOT NULL CHECK (length(author) >= 1),
  title         TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  pinned_at     TEXT,
  pinned_reason TEXT CHECK (pinned_reason IN ('escalated','memory_source')),
  session_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_con_author  ON consultations(author, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_con_sweep   ON consultations(pinned_at, updated_at);

CREATE TABLE IF NOT EXISTS consultation_messages (
  id              TEXT PRIMARY KEY
                      CHECK (id GLOB 'msg_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  consultation_id TEXT NOT NULL REFERENCES consultations(id) ON DELETE CASCADE,
  seq             INTEGER NOT NULL,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content         TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  UNIQUE (consultation_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_msg_con ON consultation_messages(consultation_id, seq);
"""

_CON_COLS: Final[tuple[str, ...]] = (
    "id",
    "author",
    "title",
    "created_at",
    "updated_at",
    "pinned_at",
    "pinned_reason",
    "session_id",
)
_MSG_COLS: Final[tuple[str, ...]] = (
    "id",
    "consultation_id",
    "seq",
    "role",
    "content",
    "created_at",
)


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    consultation_id: str
    seq: int
    role: str
    content: str
    created_at: str

    @property
    def ref(self) -> str:
        """The address a **Memory entry** cites as its source."""
        return f"{self.consultation_id}/{self.id}"


@dataclass(frozen=True, slots=True)
class Consultation:
    id: str
    author: str
    title: str
    created_at: str
    updated_at: str
    pinned_at: str | None = None
    pinned_reason: str | None = None
    session_id: str | None = None

    @property
    def is_pinned(self) -> bool:
        return self.pinned_at is not None

    def visible_to(self, *, name: str, role: str) -> bool:
        """Its author, and admins. Nobody else — see the module docstring."""
        return self.author == name or role == "admin"


def _serialised[M: Callable[..., Any]](method: M) -> M:
    """Hold the connection's lock for the whole method (see :mod:`opspilot.dblock`)."""

    @functools.wraps(method)
    def wrapper(self: ConsultationStore, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(M, wrapper)


class ConsultationStore:
    """CRUD over ``consultations`` / ``consultation_messages``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = lock_for(conn)
        with self._lock:
            conn.executescript(_SCHEMA)
            conn.commit()

    # ── writes ───────────────────────────────────────────────────────

    @_serialised
    def start(self, *, author: str, title: str = "") -> Consultation:
        """Open a Consultation. ``author`` comes from the caller's Identity."""
        author = author.strip()
        if not author:
            raise ValueError("author is required and comes from the caller's identity")
        now = now_rfc3339()
        con = Consultation(
            id="con_" + secrets.token_hex(4),
            author=author,
            title=title.strip(),
            created_at=now,
            updated_at=now,
        )
        self._conn.execute(
            "INSERT INTO consultations (id, author, title, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (con.id, con.author, con.title, con.created_at, con.updated_at),
        )
        self._conn.commit()
        return con

    @_serialised
    def append(self, consultation_id: str, *, role: str, content: str) -> Message:
        """Append one turn. Messages are ordered by ``seq``, never renumbered."""
        if role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', not {role!r}")
        if self._get(consultation_id) is None:
            raise KeyError(f"consultation {consultation_id!r} not found")
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 FROM consultation_messages WHERE consultation_id = ?",
            (consultation_id,),
        )
        seq = int(cur.fetchone()[0])
        msg = Message(
            id="msg_" + secrets.token_hex(4),
            consultation_id=consultation_id,
            seq=seq,
            role=role,
            content=content,
            created_at=now_rfc3339(),
        )
        self._conn.execute(
            "INSERT INTO consultation_messages (id, consultation_id, seq, role, content, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (msg.id, msg.consultation_id, msg.seq, msg.role, msg.content, msg.created_at),
        )
        self._conn.execute(
            "UPDATE consultations SET updated_at = ? WHERE id = ?",
            (msg.created_at, consultation_id),
        )
        self._conn.commit()
        return msg

    @_serialised
    def pin(self, consultation_id: str, *, reason: PinReason) -> None:
        """Exempt from the retention sweep. Idempotent; the first reason sticks."""
        cur = self._conn.execute(
            "UPDATE consultations SET pinned_at = ?, pinned_reason = ? "
            "WHERE id = ? AND pinned_at IS NULL",
            (now_rfc3339(), reason, consultation_id),
        )
        if cur.rowcount == 0 and self._get(consultation_id) is None:
            raise KeyError(f"consultation {consultation_id!r} not found")
        self._conn.commit()

    @_serialised
    def escalate(self, consultation_id: str, *, session_id: str) -> None:
        """Record the Session this Consultation escalated into, and pin it.

        The Session's trace holds the reverse link and is permanent; pinning is
        what stops that link pointing at something the sweep deleted.
        """
        if self._get(consultation_id) is None:
            raise KeyError(f"consultation {consultation_id!r} not found")
        self._conn.execute(
            "UPDATE consultations SET session_id = ?, pinned_at = COALESCE(pinned_at, ?), "
            "pinned_reason = COALESCE(pinned_reason, 'escalated') WHERE id = ?",
            (session_id, now_rfc3339(), consultation_id),
        )
        self._conn.commit()

    @_serialised
    def delete(self, consultation_id: str) -> None:
        """Delete a Consultation and its messages. Pinned ones are refused."""
        con = self._get(consultation_id)
        if con is None:
            raise KeyError(f"consultation {consultation_id!r} not found")
        if con.is_pinned:
            raise ValueError(
                f"{consultation_id} is pinned ({con.pinned_reason}); something permanent cites it"
            )
        self._conn.execute(
            "DELETE FROM consultation_messages WHERE consultation_id = ?", (consultation_id,)
        )
        self._conn.execute("DELETE FROM consultations WHERE id = ?", (consultation_id,))
        self._conn.commit()

    @_serialised
    def purge(self, *, older_than_days: int = RETENTION_DAYS, now: str | None = None) -> list[str]:
        """Delete unpinned Consultations idle longer than the retention window.

        Returns the ids removed. Pinned ones are never swept, however old.
        """
        cutoff = (
            datetime.fromisoformat((now or now_rfc3339()).replace("Z", "+00:00"))
            - timedelta(days=older_than_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = self._conn.execute(
            "SELECT id FROM consultations WHERE pinned_at IS NULL AND updated_at < ?",
            (cutoff,),
        )
        ids = [str(r[0]) for r in cur.fetchall()]
        if ids:
            marks = ",".join("?" * len(ids))
            self._conn.execute(
                f"DELETE FROM consultation_messages WHERE consultation_id IN ({marks})",  # noqa: S608
                tuple(ids),
            )
            self._conn.execute(f"DELETE FROM consultations WHERE id IN ({marks})", tuple(ids))  # noqa: S608
            self._conn.commit()
        return ids

    # ── reads ────────────────────────────────────────────────────────

    @_serialised
    def get(self, consultation_id: str) -> Consultation | None:
        return self._get(consultation_id)

    @_serialised
    def messages(self, consultation_id: str) -> list[Message]:
        cur = self._conn.execute(
            "SELECT " + ", ".join(_MSG_COLS) + " FROM consultation_messages "  # noqa: S608
            "WHERE consultation_id = ? ORDER BY seq",
            (consultation_id,),
        )
        return [Message(**dict(zip(_MSG_COLS, tuple(r), strict=True))) for r in cur.fetchall()]

    @_serialised
    def message(self, message_id: str) -> Message | None:
        cur = self._conn.execute(
            "SELECT " + ", ".join(_MSG_COLS) + " FROM consultation_messages WHERE id = ?",  # noqa: S608
            (message_id,),
        )
        row = cur.fetchone()
        return Message(**dict(zip(_MSG_COLS, tuple(row), strict=True))) if row else None

    @_serialised
    def list_for(self, *, name: str, role: str, limit: int = 50) -> list[Consultation]:
        """What this caller may see: their own, or everything for an admin."""
        sql = "SELECT " + ", ".join(_CON_COLS) + " FROM consultations"  # noqa: S608
        params: tuple[Any, ...] = ()
        if role != "admin":
            sql += " WHERE author = ?"
            params = (name,)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        cur = self._conn.execute(sql, (*params, limit))
        return [Consultation(**dict(zip(_CON_COLS, tuple(r), strict=True))) for r in cur.fetchall()]

    def _get(self, consultation_id: str) -> Consultation | None:
        cur = self._conn.execute(
            "SELECT " + ", ".join(_CON_COLS) + " FROM consultations WHERE id = ?",  # noqa: S608
            (consultation_id,),
        )
        row = cur.fetchone()
        return Consultation(**dict(zip(_CON_COLS, tuple(row), strict=True))) if row else None
