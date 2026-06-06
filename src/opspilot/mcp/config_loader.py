"""Load and validate mcp-config.yaml against the schema.

The inline-secret check is **best-effort** (a footgun guard, not a guarantee):
it keeps obvious credentials out of the committed config and points you at the
``${ENV_VAR}`` pattern instead. It scans env values, command args, the server
URL, and headers — by key name *and* by known secret-token shapes — but a secret
phrased to dodge every heuristic can still slip through. Keep real secrets in the
environment, not the file.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..errors import ConfigError
from ..schemas import validate as schema_validate
from .types import McpConfig

# ``${VAR}``, ``${VAR:-}`` (empty default) and ``${VAR:-default}`` — matching the
# ${VAR:-default} expansion the loader actually supports. The default, if any, is
# captured so it can be checked too (a default can itself embed a secret).
_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z_][A-Z0-9_]*(?::-(?P<default>.*))?\}$")
_SENSITIVE_NAMES = re.compile(
    r"(token|key|secret|password|passwd|credential|auth|bearer|pat|dsn|cookie)",
    re.IGNORECASE,
)
_NONEMPTY_LITERAL = re.compile(r"\S{8,}")  # non-whitespace run ≥ 8 chars
# Known provider credential shapes — flagged regardless of the key name.
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|sk_live_|ghp_|gho_|ghs_|github_pat_|xox[bpsra]-"
    r"|AKIA[0-9A-Z]{12,}|AIza[0-9A-Za-z_\-]{10,}|secret_[A-Za-z0-9]{8,}"
    r"|ntn_[A-Za-z0-9]{8,})"
)
# user:pass@host embedded in a URL.
_URL_CREDENTIALS_RE = re.compile(r"://[^/\s:@]+:[^/\s@]+@")


def _resolve_literal(value: str) -> str | None:
    """Return the literal a value reduces to, or None if it's a safe ``${VAR}``.

    ``${VAR}`` / ``${VAR:-}`` resolve to None (a pure env reference — safe).
    ``${VAR:-default}`` resolves to ``default`` so the default is still checked.
    Anything else resolves to itself.
    """
    m = _PLACEHOLDER_RE.match(value.strip())
    if m:
        return m.group("default") or None
    return value


def _looks_like_secret(name: str, value: str) -> bool:
    literal = _resolve_literal(value)
    if literal is None:
        return False
    if _SECRET_VALUE_RE.search(literal):
        return True
    return bool(name and _SENSITIVE_NAMES.search(name) and _NONEMPTY_LITERAL.search(literal))


def _check_secret_literals(cfg: McpConfig) -> None:
    """Raise ConfigError if any config value looks like an inline secret."""
    for srv in cfg.mcps:
        for k, v in srv.env.items():
            if _looks_like_secret(k, v):
                _raise(srv.id, f"env key '{k}'")
        for k, v in srv.headers.items():
            if _looks_like_secret(k, v):
                _raise(srv.id, f"header '{k}'")
        for i, a in enumerate(srv.args):
            if _looks_like_secret("", a):
                _raise(srv.id, f"args[{i}]")
            if "=" in a:
                key, _, val = a.partition("=")
                if _looks_like_secret(key.lstrip("-"), val):
                    _raise(srv.id, f"args[{i}]")
        if srv.url and _URL_CREDENTIALS_RE.search(srv.url):
            _raise(srv.id, "url (inline user:password)")


def _raise(server_id: str, where: str) -> None:
    raise ConfigError(
        f"MCP server '{server_id}': {where} appears to contain an inline secret. "
        "Use a ${ENV_VAR} placeholder instead."
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
