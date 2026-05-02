"""Typed dataclasses mirroring ``session/schemas/{session,trace-event}.schema.json``.

Why dataclasses over pydantic models here:

* The session schema is small and stable; we already validate against the
  JSON schema at the storage boundary (manager.py / trace.py), so a
  second pydantic layer would just be ceremony.
* dataclasses round-trip cleanly to/from yaml and json with the same
  ``asdict`` shape the schemas expect — no model_dump quirks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Final, Literal

# ── Lifecycle state machine ──────────────────────────────────────────
# Mirrors ``session/SPEC.md §1``. Used by SessionManager to gate
# state transitions.
SessionStatus = Literal[
    "draft",
    "active",
    "paused",
    "aborted",
    "archived",
    "purged",
]

LIFECYCLE_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "draft": frozenset({"active", "aborted"}),
    "active": frozenset({"paused", "aborted", "archived"}),
    "paused": frozenset({"active", "aborted", "archived"}),
    "aborted": frozenset({"archived"}),
    "archived": frozenset({"purged"}),
    "purged": frozenset(),  # terminal
}


# ── Session sub-types ────────────────────────────────────────────────


@dataclass(frozen=True)
class Playbook:
    id: str
    version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptRef:
    id: str
    version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Model:
    """Mirror of session.schema.json#/properties/model.

    ``alias_used`` and ``provider_config_hash`` may be ``None`` until the
    provider resolution actually runs (PR-7).
    """

    provider_id: str
    kind: Literal[
        "ollama",
        "openrouter",
        "openai",
        "anthropic",
        "gemini",
        "grok",
        "openai_compatible",
    ]
    name: str
    version: str
    alias_used: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    provider_config_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Session ──────────────────────────────────────────────────────────


@dataclass
class Session:
    """Top-level session metadata.

    Mutable on purpose — :class:`SessionManager` updates ``status`` and
    ``updated_at`` over the lifetime of the session.
    """

    id: str
    schema_version: str
    owner: str
    playbook: Playbook
    model: Model
    status: SessionStatus
    created_at: str
    updated_at: str
    retention_class: Literal["low", "medium", "high", "critical"]
    sensitivity: Literal["public", "internal", "confidential", "restricted"]
    collaborators: list[str] = field(default_factory=list)
    prompts: list[PromptRef] = field(default_factory=list)
    parent_id: str | None = None
    tags: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Round-trip to a schema-validating dict.

        Preserves the field order from session.schema.json so the
        emitted yaml looks like the spec template.
        """
        return {
            "id": self.id,
            "schema_version": self.schema_version,
            "owner": self.owner,
            "collaborators": list(self.collaborators),
            "playbook": self.playbook.to_dict(),
            "prompts": [p.to_dict() for p in self.prompts],
            "model": self.model.to_dict(),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "parent_id": self.parent_id,
            "retention_class": self.retention_class,
            "sensitivity": self.sensitivity,
            "tags": list(self.tags),
            "labels": dict(self.labels),
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        """Build a :class:`Session` from a schema-validating dict.

        Defaults match the schema's ``default`` clauses for absent
        optional fields.
        """
        return cls(
            id=d["id"],
            schema_version=d["schema_version"],
            owner=d["owner"],
            collaborators=list(d.get("collaborators") or []),
            playbook=Playbook(**d["playbook"]),
            prompts=[PromptRef(**p) for p in (d.get("prompts") or [])],
            model=Model(**d["model"]),
            status=d["status"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            parent_id=d.get("parent_id"),
            retention_class=d["retention_class"],
            sensitivity=d["sensitivity"],
            tags=list(d.get("tags") or []),
            labels=dict(d.get("labels") or {}),
            extensions=dict(d.get("extensions") or {}),
        )


# ── Trace events ─────────────────────────────────────────────────────


TraceEventType = Literal[
    "prompt",
    "response",
    "tool_call",
    "tool_result",
    "redaction",
    "user_action",
    "system",
]


@dataclass(frozen=True)
class TraceEvent:
    """One entry in ``trace.jsonl``.

    The schema uses ``oneOf`` keyed on ``type`` so each subtype has
    different required fields. We model that as a flat dataclass plus
    classmethod factories — simpler than a union of dataclasses, and
    the trace-event.schema.json validator is the canonical gate.

    Constructor convenience methods:

    * :meth:`prompt`     — prompt event (role + content)
    * :meth:`response`   — model output (content + finish_reason)
    * :meth:`tool_call`  — tool invocation (tool + args)
    * :meth:`tool_result`— tool outcome (tool + status)
    * :meth:`redaction`  — redaction notice (pattern + count)
    * :meth:`user_action`— user interaction (action)
    * :meth:`system`     — system event (event name)

    ``session_id``, ``seq``, and ``ts`` are filled by
    :class:`TraceWriter` at write time, not at construction. Construct
    events freely; the writer stamps them.
    """

    type: TraceEventType
    payload: dict[str, Any]
    actor: str | None = None  # optional but recommended; spec accepts no actor

    # ── Factory methods ──────────────────────────────────────────────

    @classmethod
    def prompt(
        cls,
        *,
        role: Literal["system", "user", "assistant", "tool"],
        content: str,
        prompt_ref: PromptRef | None = None,
        actor: str | None = None,
    ) -> TraceEvent:
        payload: dict[str, Any] = {"role": role, "content": content}
        if prompt_ref is not None:
            payload["prompt_ref"] = prompt_ref.to_dict()
        return cls(type="prompt", payload=payload, actor=actor)

    @classmethod
    def response(
        cls,
        *,
        content: str,
        finish_reason: Literal["stop", "length", "tool_call", "content_filter", "error"],
        usage: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> TraceEvent:
        payload: dict[str, Any] = {
            "content": content,
            "finish_reason": finish_reason,
        }
        if usage is not None:
            payload["usage"] = usage
        return cls(type="response", payload=payload, actor=actor)

    @classmethod
    def tool_call(
        cls,
        *,
        tool: str,
        args: dict[str, Any],
        action_id: str | None = None,
        actor: str | None = None,
    ) -> TraceEvent:
        payload: dict[str, Any] = {"tool": tool, "args": args}
        if action_id is not None:
            payload["action_id"] = action_id
        return cls(type="tool_call", payload=payload, actor=actor)

    @classmethod
    def tool_result(
        cls,
        *,
        tool: str,
        status: Literal["ok", "failed", "timeout", "aborted"],
        action_id: str | None = None,
        exit_code: int | None = None,
        stdout_ref: str | None = None,
        stderr_ref: str | None = None,
        artifact_ids: list[str] | None = None,
        duration_ms: int | None = None,
        actor: str | None = None,
    ) -> TraceEvent:
        payload: dict[str, Any] = {"tool": tool, "status": status}
        if action_id is not None:
            payload["action_id"] = action_id
        if exit_code is not None:
            payload["exit_code"] = exit_code
        if stdout_ref is not None:
            payload["stdout_ref"] = stdout_ref
        if stderr_ref is not None:
            payload["stderr_ref"] = stderr_ref
        if artifact_ids is not None:
            payload["artifact_ids"] = list(artifact_ids)
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return cls(type="tool_result", payload=payload, actor=actor)

    @classmethod
    def redaction(
        cls,
        *,
        pattern: str,
        count: int,
        placeholder_format: str | None = None,
        actor: str | None = None,
    ) -> TraceEvent:
        payload: dict[str, Any] = {"pattern": pattern, "count": count}
        if placeholder_format is not None:
            payload["placeholder_format"] = placeholder_format
        return cls(type="redaction", payload=payload, actor=actor)

    @classmethod
    def user_action(
        cls,
        *,
        action: Literal["accept", "reject", "edit", "approve", "comment", "abort", "archive"],
        target: str | None = None,
        payload_diff: str | None = None,
        actor: str | None = None,
    ) -> TraceEvent:
        payload: dict[str, Any] = {"action": action}
        if target is not None:
            payload["target"] = target
        if payload_diff is not None:
            payload["payload_diff"] = payload_diff
        return cls(type="user_action", payload=payload, actor=actor)

    @classmethod
    def system(
        cls,
        *,
        event: Literal["state_change", "error", "policy_violation", "retention_marker"],
        details: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> TraceEvent:
        payload: dict[str, Any] = {"event": event}
        if details is not None:
            payload["details"] = dict(details)
        return cls(type="system", payload=payload, actor=actor)

    # ── Serialisation ────────────────────────────────────────────────

    def render(self, *, session_id: str, seq: int, ts: str) -> dict[str, Any]:
        """Stamp ``session_id`` / ``seq`` / ``ts`` and flatten payload.

        Called by :class:`TraceWriter` immediately before validating &
        writing the line.
        """
        out: dict[str, Any] = {
            "session_id": session_id,
            "seq": seq,
            "ts": ts,
            "type": self.type,
        }
        if self.actor is not None:
            out["actor"] = self.actor
        out.update(self.payload)
        return out
