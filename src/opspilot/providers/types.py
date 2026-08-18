"""Pydantic types shared by every provider.

Aligned with ``docs/specs/providers/SPEC.md`` §1.1 (ProviderCall / ProviderResponse) so
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

    # Unset means *not sent*. Current Anthropic models (Sonnet 5, Opus 5, Opus
    # 4.7/4.8, Fable 5) reject `temperature` / `top_p` / `top_k` outright — a
    # code-level default made it impossible for a model config to opt out, so a
    # request that named one of them failed with HTTP 400 before it ran. The
    # model config is the only thing that decides now (#172).
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int = Field(default=2000, ge=1)  # required by every provider
    seed: int | None = None
    stop: list[str] | None = None
    # Thinking comes in two shapes and the model config picks one; nothing is
    # inferred from the model name (#170, same rule as the sampling knobs above).
    #
    #   thinking="adaptive" [+ effort]  — Sonnet 5, Opus 5, Opus 4.7/4.8, Fable 5.
    #       Depth is `effort`; a token budget is rejected outright:
    #       400 — "thinking.type.enabled" is not supported.
    #   thinking_budget_tokens=N        — pre-4.6 models (e.g. Haiku 4.5), which
    #       have no `effort` and require the budget instead.
    #
    # Providers that support neither ignore both.
    thinking: Literal["adaptive"] | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    thinking_budget_tokens: int | None = None

    @property
    def thinks(self) -> bool:
        """Whether this turn asks the model to reason, under either shape."""
        return self.thinking is not None or bool(self.thinking_budget_tokens)


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
