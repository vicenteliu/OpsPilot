"""Load and validate mcp-config.yaml against the schema."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..errors import ConfigError
from ..schemas import validate as schema_validate
from .types import McpConfig

_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z_][A-Z0-9_]*\}$")  # exactly ${VAR_NAME}
_SENSITIVE_NAMES = re.compile(r"(token|key|secret|password|passwd|credential)", re.IGNORECASE)
_NONEMPTY_LITERAL = re.compile(r"\S{8,}")  # non-whitespace run ≥ 8 chars


def _check_secret_literals(cfg: McpConfig) -> None:
    """Raise ConfigError if any env value looks like an inline secret."""
    for srv in cfg.mcps:
        for k, v in srv.env.items():
            if (
                _SENSITIVE_NAMES.search(k)
                and not _PLACEHOLDER_RE.match(v)
                and _NONEMPTY_LITERAL.search(v)
            ):
                raise ConfigError(
                    f"MCP server '{srv.id}': env key '{k}' appears to contain an inline secret. "
                    "Use ${ENV_VAR} placeholder instead."
                )


def load_mcp_config(path: Path) -> McpConfig:
    """Load, schema-validate, and parse an mcp-config YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        schema_validate("mcp-config", raw)
    except Exception as exc:
        raise ConfigError(f"Invalid mcp-config at {path}: {exc}") from exc
    cfg = McpConfig.model_validate(raw)
    if cfg.global_policy.block_secrets_in_env_literals:
        _check_secret_literals(cfg)
    return cfg
