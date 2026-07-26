"""Write mcp-config.yaml when the admin adds/edits a remote MCP server (#121).

Only remote (http/sse) servers are managed from the UI; stdio servers stay
file-authored and git-reviewed (ADR-0024). This re-dumps the whole config, so
existing stdio entries (loaded and re-serialized here) survive a remote edit —
including their command/args. ruamel preserves the file's top-level comments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .types import McpConfig, McpServerConfig


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    return y


def _server_map(s: McpServerConfig) -> dict[str, Any]:
    """A server as a minimal mapping — only the fields that are actually set."""
    m: dict[str, Any] = {
        "id": s.id,
        "name": s.name,
        "transport": s.transport,
        "tools_prefix": s.tools_prefix,
        "enabled": s.enabled,
        "trust": s.trust,
    }
    if s.description:
        m["description"] = s.description
    if s.url:
        m["url"] = s.url
    if s.command:
        m["command"] = s.command
    if s.args:
        m["args"] = list(s.args)
    if s.env:
        m["env"] = dict(s.env)
    if s.headers:
        m["headers"] = dict(s.headers)
    if s.tools_allowlist is not None:
        m["tools_allowlist"] = list(s.tools_allowlist)
    if s.tools_denylist is not None:
        m["tools_denylist"] = list(s.tools_denylist)
    if s.auth and s.auth.type != "none":
        auth: dict[str, Any] = {"type": s.auth.type}
        if s.auth.env:
            auth["env"] = s.auth.env
        if s.auth.header:
            auth["header"] = s.auth.header
        m["auth"] = auth
    return m


def write_mcp_config(path: Path, cfg: McpConfig) -> None:
    """Write *cfg* to *path*, preserving the file's top-level comments if it exists."""
    y = _yaml()
    data: CommentedMap = CommentedMap()
    if path.exists():
        with path.open(encoding="utf-8") as f:
            loaded = y.load(f)
        if isinstance(loaded, CommentedMap):
            data = loaded
    data["version"] = cfg.version
    data["mcps"] = [_server_map(s) for s in cfg.mcps]
    gp = cfg.global_policy
    data["global_policy"] = {
        "default_deny_on_disabled": gp.default_deny_on_disabled,
        "block_secrets_in_env_literals": gp.block_secrets_in_env_literals,
        "audit_every_call": gp.audit_every_call,
    }
    with path.open("w", encoding="utf-8") as f:
        y.dump(data, f)
