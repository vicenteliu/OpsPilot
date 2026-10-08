"""Work item classification.

Assigns a Work item type to an input that does not declare one. Declared-first
policy: callers skip this entirely when ``work_item_type`` is already present.
Single-shot provider call — no KB retrieval, no tools. A low confidence value is
surfaced to a human-confirm step rather than auto-routed (ADR-0006).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..providers.base import ProviderProtocol
from ..providers.types import Message, SamplingParams, Usage
from ..redaction import Redactor
from ..schemas import validate as schema_validate
from .errors import OrchestratorError
from .ticket_summary import _format_ticket, _load_ticket, _parse_summary_json
from .types import PlaybookSpec

DEFAULT_CONFIDENCE_THRESHOLD = 0.7
VALID_TYPES = ("incident", "service_request")


@dataclass(frozen=True)
class ClassificationResult:
    work_item_type: str
    confidence: float
    rationale: str
    # What the call cost, so the baseline every Judgment is measured against is
    # priced from what it spent rather than assumed (ADR-0040).
    usage: Usage = field(default_factory=Usage)

    def as_dict(self) -> dict[str, Any]:
        return {
            "work_item_type": self.work_item_type,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


def declared_type(ticket_input: dict[str, Any]) -> str | None:
    """Return a validly-declared ``work_item_type`` from raw input, else None."""
    t = ticket_input.get("work_item_type")
    return t if t in VALID_TYPES else None


def classify_work_item(
    input_path: Path,
    *,
    playbook: PlaybookSpec,
    provider: ProviderProtocol,
    redactor: Redactor,
) -> ClassificationResult:
    """Classify a work item as ``incident`` vs ``service_request`` (single shot)."""
    return classify_state(render_state(input_path, redactor), playbook=playbook, provider=provider)


def render_state(input_path: Path, redactor: Redactor) -> str:
    """The redacted rendering of a work item that a model, or a Judgment, is shown."""
    return redactor.redact(_format_ticket(_load_ticket(input_path))).text


def classify_state(
    state: str,
    *,
    playbook: PlaybookSpec,
    provider: ProviderProtocol,
    timeout_ms: int = 90_000,
) -> ClassificationResult:
    """Classify an already-redacted rendering of a work item."""
    messages = [
        Message(role="system", content=playbook.system_prompt),
        Message(role="user", content=state),
    ]
    resp = provider.chat(
        messages,
        model=playbook.model.name,
        params=SamplingParams(
            temperature=playbook.model.params.get("temperature"),
            top_p=playbook.model.params.get("top_p"),
            max_tokens=playbook.model.params.get("max_tokens", 512),
        ),
        timeout_ms=timeout_ms,
    )
    parsed, err = _parse_summary_json(resp.content)
    if err is not None:
        raise OrchestratorError(f"classification parse error: {err}")
    schema_validate(playbook.output_schema, parsed)
    return ClassificationResult(
        work_item_type=parsed["work_item_type"],
        confidence=float(parsed["confidence"]),
        rationale=parsed["rationale"],
        usage=resp.usage,
    )
