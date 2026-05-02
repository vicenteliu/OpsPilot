"""Tests for the ``ingest`` and ``kb-search`` CLI subcommands.

We mock ``opspilot.providers.make_provider`` so the CLI runs without a
live Ollama daemon. The mock provider exposes only the ``embed`` method
the CLI actually uses.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Final

import pytest
from typer.testing import CliRunner

from opspilot.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_MD = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "kb" / "sop_vpn_zh.md"
SAMPLE_PDF = REPO_ROOT / "tests" / "fixtures" / "sample.pdf"

DIM: Final[int] = 768

_AUTH = ("认证", "鉴权", "auth", "authentication")
_NETWORK = ("隧道", "网络", "MTU", "NAT")


def _topic_embed(text: str) -> list[float]:
    lower = text.lower()
    a = sum(1.0 for t in _AUTH if t.lower() in lower)
    n = sum(1.0 for t in _NETWORK if t.lower() in lower)
    base = [a + 0.05, 0.30, n + 0.05]
    norm = math.sqrt(sum(x * x for x in base))
    head = [x / norm for x in base]
    return head + [0.0] * (DIM - 3)


class _MockProvider:
    """Minimal stand-in for OllamaProvider; only ``embed`` is used by CLI."""

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        return [_topic_embed(t) for t in texts]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``opspilot.cli.make_provider`` with our deterministic mock."""

    def _factory(provider_id: str = "ollama-local") -> _MockProvider:
        return _MockProvider()

    monkeypatch.setattr("opspilot.cli.make_provider", _factory)


@pytest.fixture
def opspilot_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point OPSPILOT_HOME at a clean tmp dir for each test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("OPSPILOT_HOME", str(home))
    monkeypatch.setenv("LANCEDB_CONFIG_DIR", "/tmp/lancedb-config")
    return home


# ── ingest ────────────────────────────────────────────────────────────


def test_cli_ingest_md_succeeds(
    runner: CliRunner, mock_provider: None, opspilot_home: Path
) -> None:
    result = runner.invoke(app, ["ingest", str(SAMPLE_MD)])
    assert result.exit_code == 0, result.output
    assert "ingested" in result.output
    assert "succeeded" in result.output


def test_cli_ingest_pdf_succeeds(
    runner: CliRunner, mock_provider: None, opspilot_home: Path
) -> None:
    result = runner.invoke(app, ["ingest", str(SAMPLE_PDF)])
    assert result.exit_code == 0, result.output
    assert "ingested" in result.output


def test_cli_ingest_unsupported_extension_exits_2(
    runner: CliRunner,
    mock_provider: None,
    opspilot_home: Path,
    tmp_path: Path,
) -> None:
    bad = tmp_path / "code.py"
    bad.write_text("print('hi')", encoding="utf-8")
    result = runner.invoke(app, ["ingest", str(bad)])
    assert result.exit_code == 2, result.output
    assert "ERROR" in result.output


def test_cli_ingest_with_classification_flag(
    runner: CliRunner, mock_provider: None, opspilot_home: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "ingest",
            str(SAMPLE_MD),
            "--classification",
            "public",
            "--namespace",
            "opspilot:test-kb",
        ],
    )
    assert result.exit_code == 0, result.output


def test_cli_ingest_then_unchanged_is_noop(
    runner: CliRunner, mock_provider: None, opspilot_home: Path
) -> None:
    """Second invocation prints `unchanged` instead of `ingested`."""
    r1 = runner.invoke(app, ["ingest", str(SAMPLE_MD)])
    assert r1.exit_code == 0, r1.output

    r2 = runner.invoke(app, ["ingest", str(SAMPLE_MD)])
    assert r2.exit_code == 0, r2.output
    assert "unchanged" in r2.output


# ── kb-search ────────────────────────────────────────────────────────


def test_cli_kb_search_no_results_is_clean_exit(
    runner: CliRunner, mock_provider: None, opspilot_home: Path
) -> None:
    """Empty KB → 'No matches.' and exit 0."""
    result = runner.invoke(app, ["kb-search", "anything"])
    # Empty LanceDB still works; just no rows.
    assert result.exit_code == 0
    assert "No matches" in result.output


def test_cli_ingest_then_kb_search_finds_chunk(
    runner: CliRunner, mock_provider: None, opspilot_home: Path
) -> None:
    """End-to-end: ingest + search via CLI."""
    r1 = runner.invoke(app, ["ingest", str(SAMPLE_MD)])
    assert r1.exit_code == 0, r1.output

    r2 = runner.invoke(app, ["kb-search", "VPN 认证失败", "--top-k", "3"])
    assert r2.exit_code == 0, r2.output
    # Should find at least one hit; rich-table formatted output.
    assert "Top" in r2.output  # "Top N hits for: ..."
