"""Anthropic provider — Stage 2 cloud provider.

Talks to the Anthropic API using the official ``anthropic`` SDK.
Supports chat completions only; embeddings are not available via Anthropic
(use OllamaProvider for embeddings).

Message format conversion:
* ``role=system``    → extracted into Anthropic's top-level ``system`` param
* ``role=user``      → passed through as-is
* ``role=assistant`` with tool_calls → ``tool_use`` content blocks
* ``role=tool``      → ``tool_result`` blocks inside a ``user`` message;
                       consecutive tool messages are batched into one user turn
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import Anthropic, APIError

from ..errors import ProviderError
from .types import ChatResponse, FinishReason, Message, SamplingParams, ToolCall, ToolDef, Usage

# Map Anthropic stop_reason values to our FinishReason enum.
_STOP_REASON_MAP: dict[str, FinishReason] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_call",
    "stop_sequence": "stop",
}


def _map_stop_reason(raw: str | None) -> FinishReason:
    if not raw:
        return "stop"
    return _STOP_REASON_MAP.get(raw, "stop")


class AnthropicProvider:
    """Concrete provider talking to the Anthropic API."""

    provider_id: str = "anthropic-claude"
    kind: str = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ProviderError(
                "Anthropic API key not found. Set ANTHROPIC_API_KEY env var or pass api_key.",
                error_code="missing_api_key",
            )
        self._client = Anthropic(api_key=resolved_key)

    # ── Health ────────────────────────────────────────────────────────

    def health_probe(self) -> bool:
        """Return True if the client was initialised successfully."""
        return self._client is not None

    # ── Chat ──────────────────────────────────────────────────────────

    def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        params: SamplingParams,
        tools: list[ToolDef] | None = None,
        timeout_ms: int = 90_000,
    ) -> ChatResponse:
        system_parts: list[str] = []
        anthropic_messages: list[dict[str, Any]] = []

        # Separate system messages; batch consecutive tool messages.
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.role == "system":
                if msg.content:
                    system_parts.append(msg.content)
                i += 1
                continue

            if msg.role == "tool":
                # Collect all consecutive tool messages into one user turn.
                tool_results: list[dict[str, Any]] = []
                while i < len(messages) and messages[i].role == "tool":
                    t = messages[i]
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": t.tool_call_id or "",
                            "content": t.content,
                        }
                    )
                    i += 1
                anthropic_messages.append({"role": "user", "content": tool_results})
                continue

            if msg.role == "assistant" and msg.tool_calls:
                content_blocks: list[dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
                i += 1
                continue

            # Plain user or assistant message.
            anthropic_messages.append({"role": msg.role, "content": msg.content})
            i += 1

        system_text = "\n\n".join(system_parts)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": params.max_tokens,
            "messages": anthropic_messages,
        }
        if system_text:
            kwargs["system"] = system_text
        if params.temperature is not None:
            kwargs["temperature"] = params.temperature
        elif params.top_p is not None:
            kwargs["top_p"] = params.top_p
        if params.stop:
            kwargs["stop_sequences"] = params.stop
        if tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]

        try:
            response = self._client.messages.create(timeout=timeout_ms / 1000, **kwargs)
        except APIError as e:
            raise ProviderError(
                f"Anthropic API error: {e}",
                error_code="api_error",
            ) from e

        # Extract content and tool calls from response blocks.
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input) if block.input else {},
                    )
                )

        # Cost estimate for claude-sonnet-4 pricing (approximate).
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost_usd = (input_tokens * 3 + output_tokens * 15) / 1_000_000

        return ChatResponse(
            content="".join(text_parts),
            finish_reason=_map_stop_reason(response.stop_reason),
            tool_calls=tool_calls if tool_calls else None,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            ),
        )

    # ── Embeddings ────────────────────────────────────────────────────

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise ProviderError(
            "Anthropic does not support embeddings; use OllamaProvider",
            error_code="not_supported",
        )
