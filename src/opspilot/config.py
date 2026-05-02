"""Stage 1 configuration loading.

Stage 1 PR-1 only needs the home directory and a few env vars; later PRs add
``~/.opspilot/config.yaml`` parsing for KB / provider registry overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_LOG_LEVEL = "INFO"


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved runtime configuration."""

    home: Path
    ollama_base_url: str = DEFAULT_OLLAMA_URL
    log_level: str = DEFAULT_LOG_LEVEL


def load_config() -> Config:
    """Load Stage 1 config from environment variables only."""
    home_str = os.environ.get("OPSPILOT_HOME")
    home = Path(home_str).expanduser() if home_str else Path.home() / ".opspilot"
    return Config(
        home=home,
        ollama_base_url=os.environ.get("OPSPILOT_OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL),
        log_level=os.environ.get("OPSPILOT_LOG_LEVEL", DEFAULT_LOG_LEVEL),
    )


def ensure_home(home: Path) -> list[Path]:
    """Create the ``~/.opspilot/`` subtree. Returns the list of dirs touched."""
    subdirs = ("kb", "sessions", "audit", "logs")
    created: list[Path] = []
    for sub in subdirs:
        p = home / sub
        p.mkdir(parents=True, exist_ok=True)
        created.append(p)
    return created
