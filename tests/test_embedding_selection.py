"""Embedding provider selection: OpenAI by default, Ollama on request."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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


class _FakeOpenAI:
    def __init__(self, api_key: str) -> None: ...

    embeddings = SimpleNamespace(
        create=lambda **kw: SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1] * kw["dimensions"])]
        )
    )


def _fake_openai_module() -> SimpleNamespace:
    return SimpleNamespace(OpenAI=_FakeOpenAI)


# ── Default path ─────────────────────────────────────────────────────


def test_openai_is_the_default_when_a_key_is_set() -> None:
    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "sk-x"}, clear=True),
        patch.dict("sys.modules", {"openai": _fake_openai_module()}),
    ):
        fn, status = resolve_embedding(_cfg())
        vec = fn("hello")
    assert status.provider == "openai"
    assert status.model == "openai/text-embedding-3-small"
    assert status.fallback_active is False
    assert status.warning is None
    assert len(vec) == EMBED_DIM  # dimensions param aligns to the table


def test_openai_embed_model_override_is_reflected_in_the_status() -> None:
    env = {"OPENAI_API_KEY": "sk-x", "OPSPILOT_OPENAI_EMBED_MODEL": "text-embedding-3-large"}
    with (
        patch.dict(os.environ, env, clear=True),
        patch.dict("sys.modules", {"openai": _fake_openai_module()}),
    ):
        _fn, status = resolve_embedding(_cfg())
    assert status.model == "openai/text-embedding-3-large"


def test_falls_back_to_ollama_when_no_openai_key() -> None:
    with (
        patch("opspilot.embedding.make_provider", return_value=_FakeOllama(True)),
        patch.dict(os.environ, {}, clear=True),
    ):
        fn, status = resolve_embedding(_cfg())
    assert status.provider == "ollama"
    assert status.model == "ollama-local/nomic-embed-text"
    assert status.fallback_active is True
    assert status.warning and "No OPENAI_API_KEY" in status.warning
    assert len(fn("hello")) == EMBED_DIM


# ── Explicit selection ───────────────────────────────────────────────


def test_explicit_ollama_wins_over_a_present_openai_key() -> None:
    """The whole point of the knob: local embeddings while keeping the key."""
    env = {"OPENAI_API_KEY": "sk-x", "OPSPILOT_EMBED_PROVIDER": "ollama"}
    with (
        patch("opspilot.embedding.make_provider", return_value=_FakeOllama(True)),
        patch.dict(os.environ, env, clear=True),
    ):
        _fn, status = resolve_embedding(_cfg())
    assert status.provider == "ollama"
    assert status.fallback_active is False
    assert status.warning is None


def test_explicit_ollama_does_not_silently_switch_to_openai_when_down() -> None:
    """Swapping embedders behind the operator's back is what poisons a KB."""
    env = {"OPENAI_API_KEY": "sk-x", "OPSPILOT_EMBED_PROVIDER": "ollama"}
    with (
        patch("opspilot.embedding.make_provider", return_value=_FakeOllama(False)),
        patch.dict(os.environ, env, clear=True),
    ):
        fn, status = resolve_embedding(_cfg())
        with pytest.raises(RuntimeError, match="unreachable"):
            fn("hello")
    assert status.provider == "ollama"
    assert status.warning and "OPSPILOT_EMBED_PROVIDER=ollama" in status.warning


def test_explicit_openai_without_a_key_fails_at_the_call_site() -> None:
    with patch.dict(os.environ, {"OPSPILOT_EMBED_PROVIDER": "openai"}, clear=True):
        fn, status = resolve_embedding(_cfg())
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
            fn("hello")
    assert status.provider == "openai"
    assert status.warning is not None


def test_unknown_provider_value_is_ignored_and_reported() -> None:
    env = {"OPENAI_API_KEY": "sk-x", "OPSPILOT_EMBED_PROVIDER": "cohere"}
    with (
        patch.dict(os.environ, env, clear=True),
        patch.dict("sys.modules", {"openai": _fake_openai_module()}),
    ):
        _fn, status = resolve_embedding(_cfg())
    assert status.provider == "openai"  # fell through to the default
    assert status.warning and "ignoring it" in status.warning


# ── Neither backend available ────────────────────────────────────────


def test_no_key_and_ollama_down_reports_why() -> None:
    with (
        patch("opspilot.embedding.make_provider", return_value=_FakeOllama(False)),
        patch.dict(os.environ, {}, clear=True),
    ):
        fn, status = resolve_embedding(_cfg())
        with pytest.raises(RuntimeError, match="No OPENAI_API_KEY"):
            fn("hello")
    assert status.provider == "ollama"
    assert status.fallback_active is True


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
