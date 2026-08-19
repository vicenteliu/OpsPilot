"""The CLI and the API must resolve the same embedder.

They did not. `opspilot ingest`'s `--embedding-model` was a fixed typer default
(`ollama-local/nomic-embed-text-v2-moe@2026-04`) that never consulted the
environment, while the API called `resolve_embedding`, which selects OpenAI
whenever `OPENAI_API_KEY` is set. On the README's own path — `init`, `ingest`,
`serve` — any user with an OpenAI key got a hard refusal at startup, because
`serve` would not open the table `ingest` had just written under a different
embedder.

Vectors from two embedders are not comparable, so the refusal is right. The
defect was that two entry points to one product chose differently.
"""

from __future__ import annotations

import pytest

from opspilot.cli import _kb_embedding
from opspilot.config import load_config
from opspilot.embedding import resolve_embedding


@pytest.mark.parametrize(
    ("openai_key", "requested"),
    [
        ("sk-test-key", None),  # the combination that broke: a key, no explicit ask
        (None, None),
        ("sk-test-key", "ollama"),
        (None, "openai"),
    ],
)
def test_the_cli_records_what_the_api_resolves(
    monkeypatch: pytest.MonkeyPatch, openai_key: str | None, requested: str | None
) -> None:
    if openai_key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", openai_key)
    if requested is None:
        monkeypatch.delenv("OPSPILOT_EMBED_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("OPSPILOT_EMBED_PROVIDER", requested)

    cfg = load_config()
    _, api = resolve_embedding(cfg)
    _, cli_reference = _kb_embedding(cfg, None, cfg.embed_model)
    assert cli_reference == api.model


def test_an_explicit_pin_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--embedding-model` keeps meaning what it always meant."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.delenv("OPSPILOT_EMBED_PROVIDER", raising=False)
    cfg = load_config()
    _, reference = _kb_embedding(cfg, "ollama-local/pinned-model@2026-01", "pinned-model")
    assert reference == "ollama-local/pinned-model@2026-01"
