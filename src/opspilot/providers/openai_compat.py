"""OpenAI-compatible provider — supports OpenAI, OpenRouter, and Gemini.

All three services expose the OpenAI chat completions API, so one provider
class handles all of them. Differentiate by ``base_url`` and ``api_key``:

* OpenAI     — https://api.openai.com/v1         (OPENAI_API_KEY)
* OpenRouter — https://openrouter.ai/api/v1      (OPENROUTER_API_KEY)
* Gemini     — https://generativelanguage.googleapis.com/v1beta/openai
                                                  (GEMINI_API_KEY)
"""

from __future__ import annotations

import os
from typing import Any

from openai import APIError, OpenAI

from ..errors import ProviderError
from .types import ChatResponse, FinishReason, Message, SamplingParams, ToolCall, ToolDef, Usage

_DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}

_FINISH_REASON_MAP: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_call",
    "content_filter": "content_filter",
}


def _map_finish_reason(raw: str | None) -> FinishReason:
    if not raw:
        return "stop"
    return _FINISH_REASON_MAP.get(raw, "stop")


class OpenAIProvider:
    """Provider for OpenAI-compatible APIs (OpenAI, OpenRouter, Gemini)."""

    kind: str = "openai"

    def __init__(
        self,
        provider_id: str = "openai",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.provider_id = provider_id

        # Resolve api_key: explicit arg → env var named after provider → generic fallback.
        env_key = f"{provider_id.upper().replace('-', '_')}_API_KEY"
        resolved_key = api_key or os.environ.get(env_key)
        if not resolved_key:
            raise ProviderError(
                f"API key for '{provider_id}' not found. Set {env_key} env var or pass api_key.",
                error_code="missing_api_key",
            )

        # Resolve base_url: explicit arg → known default → OpenAI default.
        resolved_url = base_url or _DEFAULT_BASE_URLS.get(provider_id.split("-")[0])
        self._client = OpenAI(api_key=resolved_key, base_url=resolved_url)

    # ── Health ────────────────────────────────────────────────────────

    def health_probe(self) -> bool:
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
        openai_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "tool":
                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id or "",
                        "content": msg.content,
                    }
                )
            elif msg.role == "assistant" and msg.tool_calls:
                content: Any = msg.content or None
                openai_messages.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": str(tc.arguments)},
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
            else:
                openai_messages.append({"role": msg.role, "content": msg.content})

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": params.max_tokens,
            "timeout": timeout_ms / 1000,
        }
        if params.temperature is not None:
            kwargs["temperature"] = params.temperature
        if params.top_p is not None:
            kwargs["top_p"] = params.top_p
        if params.stop:
            kwargs["stop"] = params.stop
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        try:
            response = self._client.chat.completions.create(**kwargs)
        except APIError as e:
            raise ProviderError(f"OpenAI-compatible API error: {e}", error_code="api_error") from e

        choice = response.choices[0]
        msg_out = choice.message
        text = msg_out.content or ""

        tool_calls: list[ToolCall] = []
        if msg_out.tool_calls:
            import json as _json

            for tc in msg_out.tool_calls:
                try:
                    args = _json.loads(tc.function.arguments)
                except Exception:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        return ChatResponse(
            content=text,
            finish_reason=_map_finish_reason(choice.finish_reason),
            tool_calls=tool_calls if tool_calls else None,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=0.0,
            ),
        )

    # ── Embeddings ────────────────────────────────────────────────────

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise ProviderError(
            "Use OllamaProvider for embeddings",
            error_code="not_supported",
        )
