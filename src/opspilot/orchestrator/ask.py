"""Decision 5 (ADR-0040): the ask, the one decision left to a language model.

When decision 4 stands at ``no``, the Work item does not say enough for an
engineer to start. The summary waits, and the ask Playbook's model writes one
message asking the reporter for what is missing (#229). It sees the same
redacted rendering every Judgment sees.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..providers.base import ProviderProtocol
from ..providers.types import Message, SamplingParams, Usage
from ..schemas import validate as schema_validate
from .errors import OrchestratorError
from .ticket_summary import _parse_summary_json
from .types import PlaybookSpec


@dataclass(frozen=True)
class Ask:
    text: str
    usage: Usage


def write_ask(
    state: str, *, playbook: PlaybookSpec, provider: ProviderProtocol, timeout_ms: int = 90_000
) -> Ask:
    """Write the one message that asks the reporter for what the Work item is missing."""
    params = playbook.model.params
    resp = provider.chat(
        [
            Message(role="system", content=playbook.system_prompt),
            Message(role="user", content=state),
        ],
        model=playbook.model.name,
        params=SamplingParams(
            temperature=params.get("temperature"),
            top_p=params.get("top_p"),
            max_tokens=params.get("max_tokens", 512),
            thinking=params.get("thinking"),
            effort=params.get("effort"),
        ),
        timeout_ms=timeout_ms,
    )
    parsed, err = _parse_summary_json(resp.content)
    if err is not None:
        raise OrchestratorError(f"ask parse error: {err}")
    schema_validate(playbook.output_schema, parsed)
    return Ask(text=str(parsed["ask"]).strip(), usage=resp.usage)
