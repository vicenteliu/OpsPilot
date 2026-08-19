"""The CLI and the API must name the same human the same way.

Found by the second end-to-end run: a Working set opened in the web UI was
invisible to ``opspilot workingset status``, because the API wrote it as
``local-dev`` and the CLI looked for ``cli:<osuser>``. Both names were
deliberate; the split between them was not.
"""

from __future__ import annotations

import getpass
from pathlib import Path

import pytest

from opspilot.auth.store import AuthStore
from opspilot.cli import _cli_actor
from opspilot.kb.storage_init import init_sqlite


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    monkeypatch.delenv("OPSPILOT_API_TOKEN", raising=False)
    (tmp_path / "kb").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _add_user(home: Path) -> None:
    store = AuthStore(init_sqlite(home / "kb" / "sqlite.db"))
    store.upsert_user(username="alice", role="admin", auth_source="local", password="pw")


def test_an_unconfigured_install_answers_the_same_name_the_api_does(home: Path) -> None:
    # This is the condition auth.deps falls back on: no users, no service token.
    assert _cli_actor() == "local-dev"


def test_a_home_without_a_database_is_still_unconfigured(home: Path) -> None:
    assert not (home / "kb" / "sqlite.db").exists()
    assert _cli_actor() == "local-dev"


def test_once_a_user_exists_the_cli_stops_claiming_to_be_the_dev_identity(home: Path) -> None:
    _add_user(home)
    assert _cli_actor() == f"cli:{getpass.getuser()}"


def test_a_service_token_alone_is_enough_to_stop_it(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No users, but the API would authenticate a bearer caller rather than fall
    # back — so the CLI must not borrow the fallback name either.
    monkeypatch.setenv("OPSPILOT_API_TOKEN", "t" * 32)
    assert _cli_actor() == f"cli:{getpass.getuser()}"
