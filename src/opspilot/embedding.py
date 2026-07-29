"""Embedding-provider selection: OpenAI by default, Ollama on request.

The active embedder is chosen once at startup, never per call, so every
vector in one KB comes from the same model. ``OPSPILOT_EMBED_PROVIDER``
picks explicitly (``openai`` | ``ollama``); unset, an ``OPENAI_API_KEY``
selects OpenAI and its absence falls back to a local Ollama.

An explicit choice is honoured even when it cannot be served: asking for
Ollama and finding it down does not silently switch to OpenAI, because the
two produce incomparable vectors and the swap would quietly poison the KB.
:meth:`LanceStore.open_or_create` enforces the other half of that rule — it
refuses to open a dataset built by a different embedder.
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
_PROVIDER_ENV = "OPSPILOT_EMBED_PROVIDER"


@dataclass(frozen=True)
class EmbedStatus:
    """Which embedding backend is active and any user-facing warning."""

    provider: str  # "openai" | "ollama"
    model: str  # canonical reference recorded in the KB
    fallback_active: bool  # not on OpenAI, and did not ask not to be
    warning: str | None


def resolve_embedding(cfg: Config) -> tuple[EmbedFn, EmbedStatus]:
    """Pick the embedding backend once at startup."""
    requested = (os.environ.get(_PROVIDER_ENV) or "").strip().lower()
    openai_key = os.environ.get("OPENAI_API_KEY")

    ignored: str | None = None
    if requested and requested not in ("openai", "ollama"):
        ignored = (
            f"{_PROVIDER_ENV}={requested!r} is not 'openai' or 'ollama' — ignoring it "
            "and selecting the default way."
        )
        logger.warning(ignored)
        requested = ""

    if requested == "ollama" or (not requested and not openai_key):
        return _use_ollama(cfg, explicit=bool(requested), extra=ignored)
    return _use_openai(openai_key, extra=ignored)


def _use_openai(api_key: str | None, *, extra: str | None) -> tuple[EmbedFn, EmbedStatus]:
    model = os.environ.get("OPSPILOT_OPENAI_EMBED_MODEL", _DEFAULT_OPENAI_EMBED_MODEL)
    ref = f"openai/{model}"

    if not api_key:  # only reachable via an explicit request
        warning = _join(
            extra,
            f"{_PROVIDER_ENV}=openai but OPENAI_API_KEY is not set — embeddings (KB "
            "ingest and search) will fail until it is.",
        )
        logger.warning(warning)
        return _failing_embed(warning), EmbedStatus("openai", ref, False, warning)

    def openai_embed(text: str) -> list[float]:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(model=model, input=[text], dimensions=EMBED_DIM)
        return list(resp.data[0].embedding)

    return openai_embed, EmbedStatus("openai", ref, False, extra)


def _use_ollama(cfg: Config, *, explicit: bool, extra: str | None) -> tuple[EmbedFn, EmbedStatus]:
    ref = f"ollama-local/{cfg.embed_model}"
    ollama = make_provider("ollama-local", base_url=cfg.ollama_base_url)
    try:
        healthy = ollama.health_probe()
    except Exception:  # noqa: BLE001 — an unreachable Ollama is the case we handle
        healthy = False

    if not healthy:
        reason = (
            f"{_PROVIDER_ENV}=ollama but Ollama is unreachable at {cfg.ollama_base_url}"
            if explicit
            else f"No OPENAI_API_KEY is set and Ollama is unreachable at {cfg.ollama_base_url}"
        )
        warning = _join(
            extra,
            f"{reason} — embeddings (KB ingest and search) will fail until one is "
            "available. An explicit provider is never silently swapped: vectors from "
            "two embedders are not comparable.",
        )
        logger.warning(warning)
        return _failing_embed(warning), EmbedStatus("ollama", ref, not explicit, warning)

    def ollama_embed(text: str) -> list[float]:
        return ollama.embed([text], model=cfg.embed_model)[0]

    if explicit:
        return ollama_embed, EmbedStatus("ollama", ref, False, extra)

    warning = _join(
        extra,
        f"No OPENAI_API_KEY is set — embeddings use the local Ollama model "
        f"'{cfg.embed_model}' instead of the OpenAI default. Do NOT mix embedders in "
        "one knowledge base; a KB built under one is not searchable under the other.",
    )
    logger.warning(warning)
    return ollama_embed, EmbedStatus("ollama", ref, True, warning)


def _failing_embed(reason: str) -> EmbedFn:
    """An embed function that reports why it cannot work, at the call site."""

    def embed(text: str) -> list[float]:
        raise RuntimeError(reason)

    return embed


def _join(extra: str | None, message: str) -> str:
    return f"{extra} {message}" if extra else message
