"""Provider factory.

Dispatches by ``provider_id`` prefix or explicit ``kind`` kwarg.
Supported kinds:
  * ``ollama`` / ``ollama-local`` — local Ollama daemon
  * ``anthropic`` / ``anthropic-claude`` — Anthropic cloud API (Stage 2)

Keeping the factory here means caller code can write::

    from opspilot.providers import make_provider
    p = make_provider("ollama-local")

and not be rewritten when new providers arrive.
"""

from __future__ import annotations

from ..config import load_config
from ..errors import ConfigError
from .anthropic import AnthropicProvider
from .base import ProviderProtocol
from .ollama import OllamaProvider


def _infer_kind(provider_id: str) -> str:
    """Infer provider kind from provider_id prefix."""
    if provider_id.startswith("anthropic"):
        return "anthropic"
    return "ollama"


def make_provider(
    provider_id: str = "ollama-local",
    *,
    kind: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ProviderProtocol:
    """Build a provider instance by id.

    ``kind`` overrides the inferred kind. Pass ``kind="anthropic"`` to
    explicitly select the Anthropic provider regardless of provider_id.
    """
    resolved_kind = kind if kind is not None else _infer_kind(provider_id)

    if resolved_kind == "anthropic":
        return AnthropicProvider(api_key=api_key)

    if resolved_kind in ("ollama", "ollama-local"):
        cfg = load_config()
        return OllamaProvider(
            base_url=base_url or cfg.ollama_base_url,
            api_key=api_key,
        )

    raise ConfigError(
        f"Provider kind '{resolved_kind}' (from provider_id='{provider_id}') is not supported. "
        "Supported kinds: ollama, anthropic."
    )
