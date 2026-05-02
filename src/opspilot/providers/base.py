"""ProviderProtocol — the contract every provider must satisfy.

We use ``typing.Protocol`` so neither subclassing nor ABC bookkeeping is
required; an Ollama / Anthropic / OpenAI / etc. class need only expose the
right method signatures to be used wherever ``ProviderProtocol`` is typed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import ChatResponse, Message, SamplingParams, ToolDef


@runtime_checkable
class ProviderProtocol(Protocol):
    """Minimum surface area every provider implements.

    Concrete providers *must* expose:

    * ``provider_id``  — registry id (e.g. ``"ollama-local"``)
    * ``kind``         — provider kind (e.g. ``"ollama"``, ``"anthropic"``)
    * ``chat(...)``    — chat completion
    * ``embed(...)``   — text embedding (only callable when the provider
      advertises ``capabilities.embeddings``; PR-3's Ollama always supports it)
    * ``health_probe()`` — quick liveness check
    """

    provider_id: str
    kind: str

    def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        params: SamplingParams,
        tools: list[ToolDef] | None = None,
        timeout_ms: int = 90_000,
    ) -> ChatResponse: ...

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]: ...

    def health_probe(self) -> bool: ...
