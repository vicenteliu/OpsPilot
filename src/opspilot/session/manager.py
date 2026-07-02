"""SessionManager — create / load / list sessions; enforce lifecycle.

Layout under ``<home>/sessions/<sess_id>/``::

    meta.yaml       ── session metadata (mirrors session.schema.json)
    trace.jsonl     ── append-only event log (TraceWriter)
    audit.log       ── append-only audit (AuditLog)
    artifacts/      ── content-addressed store (ArtifactStore)
    inputs/         ── reserved for caller-supplied input artifacts (PR-7)

State machine (docs/specs/session/SPEC.md §1) is enforced by :meth:`transition`;
illegal transitions raise :class:`IllegalTransition`. Every state change
is journaled to ``audit.log`` (via :class:`AuditLog`).

This module does **not** call the redactor — see PR-5/PR-7 for the
ingestion + orchestrator wiring (D6 from PR-6 plan).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..ids import new_ulid_id
from ..schemas import validate as schema_validate
from ..timeutil import now_rfc3339
from .artifact import ArtifactStore
from .audit import AuditLog
from .errors import IllegalTransition, SessionError
from .trace import TraceWriter
from .types import LIFECYCLE_TRANSITIONS, Model, Playbook, PromptRef, Session

SESSION_SCHEMA_VERSION = "1.0.0"
DEFAULT_RETENTION_CLASS = "medium"
DEFAULT_SENSITIVITY = "internal"


class SessionManager:
    """Owns ``<home>/sessions/`` and exposes session lifecycle ops."""

    def __init__(self, home: Path) -> None:
        self._home = home
        self._root = home / "sessions"

    # ── Path helpers ─────────────────────────────────────────────────

    @property
    def root(self) -> Path:
        return self._root

    def session_dir(self, session_id: str) -> Path:
        return self._root / session_id

    # ── Create / Load / List ─────────────────────────────────────────

    def create(
        self,
        *,
        owner: str,
        playbook: Playbook,
        model: Model,
        retention_class: str = DEFAULT_RETENTION_CLASS,
        sensitivity: str = DEFAULT_SENSITIVITY,
        collaborators: list[str] | None = None,
        prompts: list[PromptRef] | None = None,
        parent_id: str | None = None,
        tags: list[str] | None = None,
        labels: dict[str, str] | None = None,
        actor: str | None = None,
    ) -> Session:
        """Create a new session in ``draft`` state.

        Writes ``meta.yaml`` and an initial ``audit.log`` entry. The
        ``inputs/`` and ``artifacts/`` directories are created lazily on
        first use; ``trace.jsonl`` likewise.
        """
        sess_id = new_ulid_id("sess")
        now = now_rfc3339()
        sess = Session(
            id=sess_id,
            schema_version=SESSION_SCHEMA_VERSION,
            owner=owner,
            collaborators=list(collaborators or []),
            playbook=playbook,
            prompts=list(prompts or []),
            model=model,
            status="draft",
            created_at=now,
            updated_at=now,
            parent_id=parent_id,
            retention_class=retention_class,  # type: ignore[arg-type]
            sensitivity=sensitivity,  # type: ignore[arg-type]
            tags=list(tags or []),
            labels=dict(labels or {}),
        )

        sdir = self.session_dir(sess_id)
        sdir.mkdir(parents=True, exist_ok=False)
        (sdir / "inputs").mkdir(exist_ok=True)
        self._write_meta(sess)

        AuditLog(sdir).write(
            actor=actor or f"user:{owner}",
            action="create",
            target=sess_id,
            details={"status": "draft"},
        )
        return sess

    def load(self, session_id: str) -> Session:
        """Read ``meta.yaml`` and return the :class:`Session`."""
        path = self._meta_path(session_id)
        if not path.is_file():
            raise SessionError(f"session not found: {session_id}")
        with path.open(encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        # Keep meta strictly schema-conformant on read so corrupted files
        # surface immediately.
        schema_validate("session", d)
        return Session.from_dict(d)

    def list(self) -> list[str]:
        """Return all known session ids (insertion order ≈ filesystem order)."""
        if not self._root.is_dir():
            return []
        return sorted(p.name for p in self._root.iterdir() if p.is_dir())

    # ── Lifecycle ────────────────────────────────────────────────────

    def transition(
        self,
        session_id: str,
        to_status: str,
        *,
        actor: str | None = None,
        reason: str | None = None,
    ) -> Session:
        """Move ``session_id`` to ``to_status`` if the transition is legal.

        Updates ``meta.yaml.updated_at`` and appends an audit row. Raises
        :class:`IllegalTransition` for moves not allowed by
        ``LIFECYCLE_TRANSITIONS``.
        """
        sess = self.load(session_id)
        allowed = LIFECYCLE_TRANSITIONS.get(sess.status, frozenset())
        if to_status not in allowed:
            raise IllegalTransition(
                f"cannot transition session {session_id} from "
                f"{sess.status!r} to {to_status!r}; allowed: {sorted(allowed)}"
            )

        prev = sess.status
        sess.status = to_status  # type: ignore[assignment]
        sess.updated_at = now_rfc3339()
        self._write_meta(sess)

        AuditLog(self.session_dir(session_id)).write(
            actor=actor or f"user:{sess.owner}",
            action="transition",
            target=session_id,
            details={"from": prev, "to": to_status, "reason": reason},
        )
        return sess

    # ── Subsystem accessors ──────────────────────────────────────────

    def trace(self, session_id: str, *, validate_on_write: bool = True) -> TraceWriter:
        """Open a :class:`TraceWriter` for ``session_id``.

        Caller is responsible for using it as a context manager.
        """
        if not self._meta_path(session_id).is_file():
            raise SessionError(f"session not found: {session_id}")
        return TraceWriter(
            self.session_dir(session_id),
            session_id=session_id,
            validate_on_write=validate_on_write,
        )

    def artifacts(self, session_id: str) -> ArtifactStore:
        if not self._meta_path(session_id).is_file():
            raise SessionError(f"session not found: {session_id}")
        return ArtifactStore(self.session_dir(session_id))

    def audit(self, session_id: str) -> AuditLog:
        if not self._meta_path(session_id).is_file():
            raise SessionError(f"session not found: {session_id}")
        return AuditLog(self.session_dir(session_id))

    # ── Internal helpers ─────────────────────────────────────────────

    def _meta_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "meta.yaml"

    def _write_meta(self, sess: Session) -> None:
        d = sess.to_dict()
        # Validate before writing so a buggy field never lands on disk.
        schema_validate("session", d)
        path = self._meta_path(sess.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                _yaml_clean(d),
                f,
                sort_keys=False,
                allow_unicode=True,
            )


def _yaml_clean(d: dict[str, Any]) -> dict[str, Any]:
    """Drop None values so the emitted yaml mirrors the spec template
    (which omits absent optional fields rather than writing ``null``).

    Keeps ``parent_id: null`` because the schema explicitly allows null
    there and it's a useful affordance for branching sessions.
    """
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None and k != "parent_id":
            continue
        out[k] = v
    return out
