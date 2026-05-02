"""Pydantic types shared by every provider.

Aligned with ``providers/SPEC.md`` §1.1 (ProviderCall / ProviderResponse) so
the same types serve every concrete provider implementation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FinishReason = Literal["stop", "length", "tool_call", "content_filter", "error"]
Role = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    """One tool the model wants the runtime to execute."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]


class ToolDef(BaseModel):
    """A tool advertised to the model. ``parameters`` is a JSON Schema."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters: dict[str, Any]


class Message(BaseModel):
    """A single chat message."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # required when role == "tool"
    name: str | None = None  # optional; some providers display this


class SamplingParams(BaseModel):
    """Sampling knobs. Defaults align with our spec's session-meta template."""

    model_config = ConfigDict(frozen=True)

    temperature: float = Field(0.2, ge=0, le=2)
    top_p: float = Field(0.9, ge=0, le=1)
    max_tokens: int = Field(2000, ge=1)
    seed: int | None = None
    stop: list[str] | None = None


class Usage(BaseModel):
    """Token + cost accounting from one provider call."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ChatResponse(BaseModel):
    """Provider-agnostic chat response shape."""

    model_config = ConfigDict(frozen=True)

    content: str
    finish_reason: FinishReason
    tool_calls: list[ToolCall] | None = None
    usage: Usage = Field(default_factory=Usage)
