"""Embedding-provider selection with an Ollama → OpenAI fallback.

Embeddings default to Ollama (local, no key). If Ollama is unreachable at
startup and an OpenAI key is configured, the whole session falls back to
OpenAI embeddings and surfaces a prominent notice — Ollama and OpenAI
vectors live in different spaces, so they must never be mixed inside one
KB (switching providers means the KB should be rebuilt). The choice is
made once at startup, never per call, to keep every KB internally
consistent.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from .config import Config
from .providers.registry import make_provider

logger = logging.getLogger("opspilot.embedding")

EmbedFn = Callable[[str], list[float]]

# Must match the LanceDB table dimension opened in the API app (768). OpenAI
# text-embedding-3-* support a `dimensions` param to emit exactly this width.
EMBED_DIM = 768
_DEFAULT_OPENAI_EMBED_MODEL = "text-embedding-3-small"


@dataclass(frozen=True)
class EmbedStatus:
    """Which embedding backend is active and any user-facing warning."""

    provider: str  # "ollama" | "openai"
    fallback_active: bool
    warning: str | None


def resolve_embedding(cfg: Config) -> tuple[EmbedFn, EmbedStatus]:
    """Pick the embedding backend once at startup (Ollama, else OpenAI)."""
    ollama = make_provider("ollama-local", base_url=cfg.ollama_base_url)
    try:
        ollama_ok = ollama.health_probe()
    except Exception:  # noqa: BLE001 — unreachable Ollama is the case we handle
        ollama_ok = False

    if ollama_ok:

        def ollama_embed(text: str) -> list[float]:
            return ollama.embed([text], model=cfg.embed_model)[0]

        return ollama_embed, EmbedStatus(provider="ollama", fallback_active=False, warning=None)

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        model = os.environ.get("OPSPILOT_OPENAI_EMBED_MODEL", _DEFAULT_OPENAI_EMBED_MODEL)

        def openai_embed(text: str) -> list[float]:
            from openai import OpenAI

            client = OpenAI(api_key=openai_key)
            resp = client.embeddings.create(model=model, input=[text], dimensions=EMBED_DIM)
            return list(resp.data[0].embedding)

        warning = (
            f"Ollama embeddings are unavailable — falling back to OpenAI '{model}' "
            f"({EMBED_DIM}-dim). Do NOT mix embedders in one knowledge base: if this KB "
            "was built with Ollama, rebuild it under the current provider or retrieval "
            "will be unreliable."
        )
        logger.warning(warning)
        return openai_embed, EmbedStatus(provider="openai", fallback_active=True, warning=warning)

    # Neither backend available — keep the Ollama fn so calls fail loudly, but
    # surface why up front.
    def failing_embed(text: str) -> list[float]:
        return ollama.embed([text], model=cfg.embed_model)[0]

    warning = (
        "Ollama is unreachable and no OPENAI_API_KEY is set — embeddings (KB ingest "
        "and search) will fail until one is available."
    )
    logger.warning(warning)
    return failing_embed, EmbedStatus(provider="ollama", fallback_active=False, warning=warning)
