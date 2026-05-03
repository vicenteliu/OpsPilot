"""OpsPilot configuration loading.

Reads ``~/.opspilot/config.yaml`` (optional), then overlays environment
variables. All fields have sensible defaults so the file is never required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_LOG_LEVEL = "INFO"


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved runtime configuration."""

    home: Path
    ollama_base_url: str = DEFAULT_OLLAMA_URL
    log_level: str = DEFAULT_LOG_LEVEL
    anthropic_api_key: str | None = None
    embed_model: str = "nomic-embed-text-v2-moe"
    playbooks_dir: Path | None = None  # defaults to ./playbooks at runtime
    ui_modules: dict[str, bool] = field(default_factory=lambda: {"run": True, "history": True})


def load_config() -> Config:
    """Load config from optional YAML file, then overlay environment variables."""
    home_str = os.environ.get("OPSPILOT_HOME")
    home = Path(home_str).expanduser() if home_str else Path.home() / ".opspilot"

    # Load optional YAML config file.
    yaml_data: dict[str, Any] = {}
    config_path = home / "config.yaml"
    if config_path.is_file():
        with config_path.open(encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                yaml_data = loaded

    # Resolve each field: env var takes precedence over yaml, yaml over default.
    ollama_base_url = (
        os.environ.get("OPSPILOT_OLLAMA_BASE_URL")
        or yaml_data.get("ollama_base_url")
        or DEFAULT_OLLAMA_URL
    )

    log_level = (
        os.environ.get("OPSPILOT_LOG_LEVEL") or yaml_data.get("log_level") or DEFAULT_LOG_LEVEL
    )

    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY") or yaml_data.get("anthropic_api_key")

    embed_model = yaml_data.get("embed_model") or "nomic-embed-text-v2-moe"

    playbooks_dir_raw = os.environ.get("OPSPILOT_PLAYBOOKS_DIR") or yaml_data.get("playbooks_dir")
    playbooks_dir = Path(playbooks_dir_raw).expanduser() if playbooks_dir_raw else None

    # ui.modules dict from yaml; default to {"run": True}.
    ui_raw = yaml_data.get("ui") or {}
    ui_modules_raw = ui_raw.get("modules") if isinstance(ui_raw, dict) else None
    ui_modules: dict[str, bool] = (
        {str(k): bool(v) for k, v in ui_modules_raw.items()}
        if isinstance(ui_modules_raw, dict)
        else {"run": True, "history": True}
    )

    return Config(
        home=home,
        ollama_base_url=str(ollama_base_url),
        log_level=str(log_level),
        anthropic_api_key=str(anthropic_api_key) if anthropic_api_key else None,
        embed_model=str(embed_model),
        playbooks_dir=playbooks_dir,
        ui_modules=ui_modules,
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
