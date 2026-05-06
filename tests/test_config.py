"""Tests for config.py — load_config and ensure_home."""

from __future__ import annotations

from pathlib import Path

import yaml

from opspilot.config import DEFAULT_LOG_LEVEL, DEFAULT_OLLAMA_URL, ensure_home, load_config


def test_load_config_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPSPILOT_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OPSPILOT_LOG_LEVEL", raising=False)
    monkeypatch.delenv("OPSPILOT_PLAYBOOKS_DIR", raising=False)
    cfg = load_config()
    assert cfg.home == tmp_path
    assert cfg.ollama_base_url == DEFAULT_OLLAMA_URL
    assert cfg.log_level == DEFAULT_LOG_LEVEL
    assert cfg.anthropic_api_key is None


def test_load_config_env_overrides(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("OPSPILOT_OLLAMA_BASE_URL", "http://remote:11434")
    monkeypatch.setenv("OPSPILOT_LOG_LEVEL", "DEBUG")
    cfg = load_config()
    assert cfg.anthropic_api_key == "sk-test-key"
    assert cfg.ollama_base_url == "http://remote:11434"
    assert cfg.log_level == "DEBUG"


def test_load_config_from_yaml(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPSPILOT_OLLAMA_BASE_URL", raising=False)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.dump({
            "ollama_base_url": "http://yaml-host:11434",
            "anthropic_api_key": "sk-from-yaml",
            "embed_model": "custom-embed",
        }),
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.ollama_base_url == "http://yaml-host:11434"
    assert cfg.anthropic_api_key == "sk-from-yaml"
    assert cfg.embed_model == "custom-embed"


def test_load_config_env_beats_yaml(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    monkeypatch.setenv("OPSPILOT_OLLAMA_BASE_URL", "http://env-host:11434")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.dump({"ollama_base_url": "http://yaml-host:11434"}),
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.ollama_base_url == "http://env-host:11434"


def test_load_config_playbooks_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    monkeypatch.setenv("OPSPILOT_PLAYBOOKS_DIR", str(tmp_path / "pbs"))
    cfg = load_config()
    assert cfg.playbooks_dir == tmp_path / "pbs"


def test_load_config_ui_modules_from_yaml(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.dump({"ui": {"modules": {"run": True, "history": False}}}),
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.ui_modules["run"] is True
    assert cfg.ui_modules["history"] is False


def test_load_config_invalid_yaml_falls_back(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("null\n", encoding="utf-8")
    cfg = load_config()
    assert cfg.ollama_base_url == DEFAULT_OLLAMA_URL


# ── ensure_home ────────────────────────────────────────────────────────────


def test_ensure_home_creates_subdirs(tmp_path: Path):
    home = tmp_path / ".opspilot"
    created = ensure_home(home)
    for name in ("kb", "sessions", "audit", "logs"):
        assert (home / name).is_dir()
    assert len(created) == 4


def test_ensure_home_idempotent(tmp_path: Path):
    home = tmp_path / ".opspilot"
    ensure_home(home)
    ensure_home(home)  # second call must not raise
    assert (home / "sessions").is_dir()
