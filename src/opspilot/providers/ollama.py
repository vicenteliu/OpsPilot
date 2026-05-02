"""Ollama provider — Stage 1's only provider.

Talks to a local Ollama server (default ``http://localhost:11434``). Uses:

* ``POST /v1/chat/completions`` (OpenAI-compatible) for chat — convenient for
  reusing the same response shape as the cloud providers we'll add later.
* ``POST /api/embed`` (Ollama native) for embeddings — batch endpoint
  ({"input": list, "embeddings": [[...], ...]}); supersedes the legacy
  ``/api/embeddings`` route which silently truncated context windows.
* ``GET /api/tags`` for ``health_probe()``.

No auth headers; Ollama defaults to no API key. If you front it with a
reverse proxy that *does* require auth, set ``api_key`` and we'll send a
``Authorization: Bearer …`` header.
"""

from __future__ import annotations

import json
from typing import Any, Final

import httpx

from ..errors import ProviderError
from .types import ChatResponse, FinishReason, Message, SamplingParams, ToolCall, ToolDef, Usage

DEFAULT_BASE_URL: Final[str] = "http://localhost:11434"
DEFAULT_TIMEOUT_S: Final[float] = 90.0


# Map OpenAI-style finish_reason values into our enum. Anything we don't
# recognise becomes "stop" (the safest default — the model produced output).
_FINISH_REASON_MAP: Final[dict[str, FinishReason]] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_call",
    "tool_call": "tool_call",
    "content_filter": "content_filter",
    "function_call": "tool_call",
}


def _normalize_finish_reason(raw: str | None) -> FinishReason:
    if not raw:
        return "stop"
    return _FINISH_REASON_MAP.get(raw, "stop")


class OllamaProvider:
    """Concrete provider talking to a local Ollama daemon."""

    provider_id: str = "ollama-local"
    kind: str = "ollama"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_key: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        # Allow injection for tests (e.g. httpx.MockTransport-backed Client).
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=timeout_s,
                headers=headers,
            )
            self._owns_client = True

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OllamaProvider:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── Health ────────────────────────────────────────────────────────

    def health_probe(self) -> bool:
        try:
            r = self._client.get("/api/tags", timeout=5.0)
        except (httpx.RequestError, httpx.HTTPError):
            return False
        return r.status_code == 200

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
        body: dict[str, Any] = {
            "model": model,
            "messages": [self._serialize_message(m) for m in messages],
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "stream": False,
        }
        if params.seed is not None:
            body["seed"] = params.seed
        if params.stop:
            body["stop"] = params.stop
        if tools:
            body["tools"] = [
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
            r = self._client.post(
                "/v1/chat/completions",
                json=body,
                timeout=timeout_ms / 1000.0,
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Ollama chat HTTP {e.response.status_code}: {e.response.text[:200]}",
                error_code=f"http_{e.response.status_code}",
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError("Ollama chat timeout", error_code="timeout_read") from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"Ollama chat network error: {e}", error_code="network_error"
            ) from e

        data = r.json()
        try:
            choice = data["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Ollama chat: malformed response: {data!r}") from e

        return ChatResponse(
            content=msg.get("content") or "",
            finish_reason=_normalize_finish_reason(choice.get("finish_reason")),
            tool_calls=self._extract_tool_calls(msg),
            usage=self._extract_usage(data),
        )

    # ── Embeddings ────────────────────────────────────────────────────

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        # Use Ollama's batch ``/api/embed`` endpoint. The legacy
        # ``/api/embeddings`` route is deprecated and (observed in real
        # ingest with nomic-embed-text-v2-moe on a 1.1 KB Chinese chunk)
        # silently truncates the model context, returning HTTP 500
        # ``the input length exceeds the context length``. ``/api/embed``
        # uses the model's max_position_embeddings and accepts a list of
        # inputs in one round-trip.
        if not texts:
            return []
        try:
            r = self._client.post(
                "/api/embed",
                json={"model": model, "input": texts},
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Ollama embed HTTP {e.response.status_code}: {e.response.text[:200]}",
                error_code=f"http_{e.response.status_code}",
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError("Ollama embed timeout", error_code="timeout_read") from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"Ollama embed network error: {e}", error_code="network_error"
            ) from e

        data = r.json()
        embs = data.get("embeddings")
        if not isinstance(embs, list) or len(embs) != len(texts):
            raise ProviderError(
                f"Ollama embed: malformed response (expected {len(texts)} embeddings, got {data!r})"
            )
        return [list(e) for e in embs]

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _serialize_message(m: Message) -> dict[str, Any]:
        d: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.name:
            d["name"] = m.name
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in m.tool_calls
            ]
        return d

    @staticmethod
    def _extract_tool_calls(msg: dict[str, Any]) -> list[ToolCall] | None:
        raw = msg.get("tool_calls") or []
        if not raw:
            return None
        out: list[ToolCall] = []
        for tc in raw:
            fn = tc.get("function", {})
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    # Some models emit non-JSON; preserve as opaque string field.
                    args = {"_raw": args}
            elif args is None:
                args = {}
            out.append(
                ToolCall(
                    id=tc.get("id") or "",
                    name=fn.get("name") or "",
                    arguments=args,
                )
            )
        return out

    @staticmethod
    def _extract_usage(data: dict[str, Any]) -> Usage:
        usage = data.get("usage") or {}
        return Usage(
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            # Ollama is local — zero monetary cost.
            cost_usd=0.0,
        )
