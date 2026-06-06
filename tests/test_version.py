"""Guards that the reported version stays in sync with pyproject (#26).

``opspilot.__version__`` derives from installed package metadata, so the
single source of truth is ``pyproject.toml``'s ``[project].version``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

import opspilot
from opspilot.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def test_package_version_matches_pyproject() -> None:
    assert opspilot.__version__ == _pyproject_version()


def test_tui_reexports_same_version() -> None:
    import opspilot.tui

    assert opspilot.tui.__version__ == opspilot.__version__


def test_cli_version_flag_matches() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert opspilot.__version__ in result.stdout
