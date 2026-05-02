"""Provider factory.

PR-3 only knows how to instantiate ``ollama-local``. PR-9+ extends this
into a proper registry that reads ``providers/templates/provider-registry.yaml``
and dispatches by ``kind``.

Keeping the factory here means caller code can already write::

    from opspilot.providers import make_provider
    p = make_provider("ollama-local")

and not be rewritten when the registry grows.
"""

from __future__ import annotations

from ..config import load_config
from ..errors import ConfigError
from .base import ProviderProtocol
from .ollama import OllamaProvider

# Stage 1 supports a single hard-coded provider id; PR-9+ replaces this map
# with a yaml-backed lookup.
_BUILTIN_KINDS = {"ollama", "ollama-local"}


def make_provider(
    provider_id: str = "ollama-local",
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ProviderProtocol:
    """Build a provider instance by id.

    Stage 1: only ``ollama-local`` (alias ``ollama``) is supported.
    """
    if provider_id not in _BUILTIN_KINDS:
        msg = (
            f"Provider '{provider_id}' not supported in Stage 1; "
            f"only {sorted(_BUILTIN_KINDS)} (Ollama). "
            "More providers arrive in PR-9+."
        )
        raise ConfigError(msg)

    cfg = load_config()
    return OllamaProvider(
        base_url=base_url or cfg.ollama_base_url,
        api_key=api_key,
    )
