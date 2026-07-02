"""Append-only audit log per session.

Layout::

    <session_dir>/audit.log    ── JSONL; one event per line

Used for state transitions and RBAC events; per ``docs/specs/session/SPEC.md §6``
its retention is **separate** from session content (longer by default,
e.g. 365 days). PR-6 just writes the lines; retention enforcement is
PR-9+.

Each entry::

    {"ts": "2026-05-01T10:00:00.000Z",
     "actor": "user:vicente@example.com",
     "action": "transition",
     "target": "sess_01H...",
     "details": {"from": "draft", "to": "active"}}
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..timeutil import now_rfc3339


@dataclass(frozen=True)
class AuditEntry:
    """One row in audit.log."""

    ts: str
    actor: str
    action: str
    target: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditLog:
    """Per-session append-only writer.

    Cheap to construct; the file is created lazily on first ``write``.
    Each call flushes (no buffering) — audit trails are critical, so we
    eat the durability cost.
    """

    def __init__(self, session_dir: Path) -> None:
        self._path = session_dir / "audit.log"

    @property
    def path(self) -> Path:
        return self._path

    def write(
        self,
        *,
        actor: str,
        action: str,
        target: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Append a new audit row. Returns the entry that was written."""
        entry = AuditEntry(
            ts=now_rfc3339(),
            actor=actor,
            action=action,
            target=target,
            details=dict(details or {}),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False))
            f.write("\n")
        return entry

    def read_all(self) -> list[AuditEntry]:
        """Return every entry in insertion order. Empty list if no log yet."""
        if not self._path.is_file():
            return []
        out: list[AuditEntry] = []
        with self._path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                d = json.loads(line)
                out.append(AuditEntry(**d))
        return out
