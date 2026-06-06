"""Work item classification.

Assigns a Work item type to an input that does not declare one. Declared-first
policy: callers skip this entirely when ``work_item_type`` is already present.
Single-shot provider call — no KB retrieval, no tools. A low confidence value is
surfaced to a human-confirm step rather than auto-routed (ADR-0006).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..providers.base import ProviderProtocol
from ..providers.types import Message, SamplingParams
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
    ticket = _load_ticket(input_path)
    rendered = _format_ticket(ticket)
    redacted = redactor.redact(rendered).text

    messages = [
        Message(role="system", content=playbook.system_prompt),
        Message(role="user", content=redacted),
    ]
    resp = provider.chat(
        messages,
        model=playbook.model.name,
        params=SamplingParams(
            temperature=playbook.model.params.get("temperature", 0.0),
            top_p=playbook.model.params.get("top_p", 0.9),
            max_tokens=playbook.model.params.get("max_tokens", 512),
        ),
    )
    parsed, err = _parse_summary_json(resp.content)
    if err is not None:
        raise OrchestratorError(f"classification parse error: {err}")
    schema_validate(playbook.output_schema, parsed)
    return ClassificationResult(
        work_item_type=parsed["work_item_type"],
        confidence=float(parsed["confidence"]),
        rationale=parsed["rationale"],
    )
