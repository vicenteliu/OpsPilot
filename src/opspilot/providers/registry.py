"""Provider factory.

Dispatches by ``provider_id`` prefix or explicit ``kind`` kwarg.
Supported kinds:
  * ``ollama``      — local Ollama daemon (default fallback)
  * ``anthropic``   — Anthropic cloud API
  * ``openai``      — OpenAI API
  * ``openrouter``  — OpenRouter (OpenAI-compatible)
  * ``gemini``      — Google Gemini (OpenAI-compatible endpoint)

Caller code stays stable as new providers arrive::

    from opspilot.providers import make_provider
    p = make_provider("openrouter", api_key="sk-or-...")
"""

from __future__ import annotations

from ..config import load_config
from ..errors import ConfigError
from .anthropic import AnthropicProvider
from .base import ProviderProtocol
from .ollama import OllamaProvider
from .openai_compat import OpenAIProvider

_OPENAI_COMPATIBLE_PREFIXES = ("openai", "openrouter", "gemini")


def _infer_kind(provider_id: str) -> str:
    if provider_id.startswith("anthropic"):
        return "anthropic"
    for prefix in _OPENAI_COMPATIBLE_PREFIXES:
        if provider_id.startswith(prefix):
            return "openai"
    return "ollama"


def make_provider(
    provider_id: str = "ollama-local",
    *,
    kind: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ProviderProtocol:
    """Build a provider instance by id.

    ``kind`` overrides the inferred kind.
    For openai-compatible providers the api_key env var is derived from
    the provider_id (e.g. ``OPENROUTER_API_KEY`` for ``openrouter``).
    """
    resolved_kind = kind if kind is not None else _infer_kind(provider_id)

    if resolved_kind == "anthropic":
        return AnthropicProvider(api_key=api_key)

    if resolved_kind == "openai":
        return OpenAIProvider(provider_id=provider_id, api_key=api_key, base_url=base_url)

    if resolved_kind in ("ollama", "ollama-local"):
        cfg = load_config()
        return OllamaProvider(
            base_url=base_url or cfg.ollama_base_url,
            api_key=api_key,
        )

    raise ConfigError(
        f"Provider kind '{resolved_kind}' (from provider_id='{provider_id}') is not supported. "
        "Supported kinds: ollama, anthropic, openai, openrouter, gemini."
    )
