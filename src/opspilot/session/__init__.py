"""Session subsystem.

PR-6 introduces:

* :class:`Session` — session metadata (mirrors session.schema.json).
* :class:`TraceEvent` and friends — typed wrappers for every entry that
  may appear in ``trace.jsonl`` (matches the oneOf branches of
  trace-event.schema.json).
* :class:`SessionManager` — create / load / list sessions; enforces the
  state machine in docs/specs/session/SPEC.md §1.
* :class:`TraceWriter` — append-only JSONL with auto seq + ts and per-row
  schema validation.
* :class:`ArtifactStore` — content-addressed ``art_<sha256[:16]>`` files
  + sidecar yaml meta.
* :class:`AuditLog` — append-only audit events for state changes and
  RBAC actions.
"""

from .artifact import ArtifactMeta, ArtifactStore
from .audit import AuditEntry, AuditLog
from .errors import IllegalTransition, SessionError
from .manager import SessionManager
from .trace import TraceWriter
from .types import (
    LIFECYCLE_TRANSITIONS,
    Model,
    Playbook,
    PromptRef,
    Session,
    TraceEvent,
)

__all__ = [
    "ArtifactMeta",
    "ArtifactStore",
    "AuditEntry",
    "AuditLog",
    "IllegalTransition",
    "LIFECYCLE_TRANSITIONS",
    "Model",
    "Playbook",
    "PromptRef",
    "Session",
    "SessionError",
    "SessionManager",
    "TraceEvent",
    "TraceWriter",
]
