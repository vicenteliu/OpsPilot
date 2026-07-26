"""Embedding provider selection: Ollama default, OpenAI fallback (ADR-0020)."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

from opspilot.embedding import EMBED_DIM, resolve_embedding


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(ollama_base_url="http://ollama:11434", embed_model="nomic-embed-text")


class _FakeOllama:
    def __init__(self, healthy: bool) -> None:
        self._healthy = healthy

    def health_probe(self) -> bool:
        return self._healthy

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        return [[0.5] * EMBED_DIM for _ in texts]


def test_uses_ollama_when_healthy() -> None:
    with patch("opspilot.embedding.make_provider", return_value=_FakeOllama(True)):
        fn, status = resolve_embedding(_cfg())
    assert status.provider == "ollama"
    assert status.fallback_active is False
    assert status.warning is None
    assert len(fn("hello")) == EMBED_DIM


def test_falls_back_to_openai_when_ollama_down_and_key_set() -> None:
    class _FakeOpenAI:
        def __init__(self, api_key: str) -> None: ...

        embeddings = SimpleNamespace(
            create=lambda **kw: SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1] * kw["dimensions"])]
            )
        )

    with (
        patch("opspilot.embedding.make_provider", return_value=_FakeOllama(False)),
        patch.dict(os.environ, {"OPENAI_API_KEY": "sk-x"}, clear=False),
        patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}),
    ):
        fn, status = resolve_embedding(_cfg())
        vec = fn("hello")
    assert status.provider == "openai"
    assert status.fallback_active is True
    assert status.warning and "OpenAI" in status.warning
    assert len(vec) == EMBED_DIM  # dimensions param aligns to the table


def test_warns_when_ollama_down_and_no_openai_key() -> None:
    with (
        patch("opspilot.embedding.make_provider", return_value=_FakeOllama(False)),
        patch.dict(os.environ, {}, clear=True),
    ):
        _fn, status = resolve_embedding(_cfg())
    assert status.provider == "ollama"
    assert status.fallback_active is False
    assert status.warning and "no OPENAI_API_KEY" in status.warning


def test_ollama_health_probe_exception_treated_as_down() -> None:
    class _Boom:
        def health_probe(self) -> bool:
            raise ConnectionError("refused")

    with (
        patch("opspilot.embedding.make_provider", return_value=_Boom()),
        patch.dict(os.environ, {}, clear=True),
    ):
        _fn, status = resolve_embedding(_cfg())
    assert status.warning is not None  # degraded, surfaced
