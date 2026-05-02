"""Data contracts and playbook loader for the orchestrator.

A *playbook* lives at ``playbooks/<id>/`` with::

    playbook.yaml    ── spec (id, version, model, tools, output_schema, …)
    prompt.md        ── system prompt (referenced by playbook.yaml.system_prompt)

The :class:`PlaybookSpec` dataclass mirrors the validated yaml so the rest
of the orchestrator can rely on typed fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..session.types import Model, Playbook
from .errors import PlaybookError

# ── Playbook spec ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlaybookToolSpec:
    """One tool entry from playbook.yaml#/tools."""

    name: str
    description: str


@dataclass(frozen=True)
class PlaybookLimits:
    max_turns: int = 8
    max_kb_search_results: int = 5


@dataclass(frozen=True)
class PlaybookDefaults:
    retention_class: str = "medium"
    sensitivity: str = "internal"
    kb_id: str = "opspilot:public-kb"


@dataclass(frozen=True)
class PlaybookSpec:
    """Resolved playbook with the system prompt loaded into memory."""

    id: str
    version: str
    description: str
    system_prompt: str  # the actual markdown text, not the path
    output_schema: str
    tools: list[PlaybookToolSpec]
    model: Model
    limits: PlaybookLimits
    defaults: PlaybookDefaults
    source_dir: Path

    @property
    def ref(self) -> Playbook:
        """Reference suitable for session.meta.playbook."""
        return Playbook(id=self.id, version=self.version)


def load_playbook(playbook_dir: Path) -> PlaybookSpec:
    """Read ``<dir>/playbook.yaml`` + the referenced ``prompt.md``."""
    yaml_path = playbook_dir / "playbook.yaml"
    if not yaml_path.is_file():
        raise PlaybookError(f"playbook.yaml not found at {yaml_path}")
    with yaml_path.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    for required in ("id", "version", "system_prompt", "output_schema", "model"):
        if required not in data:
            raise PlaybookError(f"playbook.yaml missing required field: {required}")

    prompt_path = playbook_dir / data["system_prompt"]
    if not prompt_path.is_file():
        raise PlaybookError(f"system_prompt path not found: {prompt_path}")
    prompt_text = prompt_path.read_text(encoding="utf-8")

    model_d = data["model"]
    model = Model(
        provider_id=model_d["provider_id"],
        kind=model_d["kind"],
        name=model_d["name"],
        version=model_d["version"],
        params=dict(model_d.get("params") or {}),
    )

    tools = [
        PlaybookToolSpec(name=t["name"], description=t.get("description", ""))
        for t in (data.get("tools") or [])
    ]

    limits_d = data.get("limits") or {}
    limits = PlaybookLimits(
        max_turns=int(limits_d.get("max_turns", 8)),
        max_kb_search_results=int(limits_d.get("max_kb_search_results", 5)),
    )

    defaults_d = data.get("defaults") or {}
    defaults = PlaybookDefaults(
        retention_class=str(defaults_d.get("retention_class", "medium")),
        sensitivity=str(defaults_d.get("sensitivity", "internal")),
        kb_id=str(defaults_d.get("kb_id", "opspilot:public-kb")),
    )

    return PlaybookSpec(
        id=data["id"],
        version=data["version"],
        description=str(data.get("description", "")),
        system_prompt=prompt_text,
        output_schema=data["output_schema"],
        tools=tools,
        model=model,
        limits=limits,
        defaults=defaults,
        source_dir=playbook_dir,
    )


# ── Run request / result ─────────────────────────────────────────────


@dataclass(frozen=True)
class RunRequest:
    """Input to :func:`run_ticket_summary`."""

    playbook: PlaybookSpec
    input_path: Path
    owner: str
    kb_id: str | None = None  # falls back to playbook.defaults.kb_id
    namespace: str | None = None  # falls back to kb_id
    classification: str | None = None  # falls back to playbook.defaults.sensitivity


@dataclass(frozen=True)
class RunResult:
    """Output of :func:`run_ticket_summary`."""

    session_id: str
    artifact_id: str | None  # None if the run aborted before producing one
    summary: dict[str, Any] = field(default_factory=dict)
    schema_valid: bool = False
    error: str | None = None
