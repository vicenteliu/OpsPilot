"""Writing mcp-config.yaml for admin-managed remote servers (#121)."""

from __future__ import annotations

from pathlib import Path

from opspilot.mcp.config_loader import load_mcp_config
from opspilot.mcp.config_writer import write_mcp_config
from opspilot.mcp.types import McpAuth, McpConfig, McpServerConfig


def _remote() -> McpServerConfig:
    return McpServerConfig(
        id="search",
        name="Search",
        transport="http",
        url="https://example.com/mcp",
        tools_prefix="mcp__search__",
        enabled=True,
        trust="community",
        auth=McpAuth(type="bearer_env", env="SEARCH_TOKEN"),
    )


def test_write_then_load_roundtrips(tmp_path: Path) -> None:
    p = tmp_path / "mcp-config.yaml"
    write_mcp_config(p, McpConfig(version="1.0.0", mcps=[_remote()]))
    back = load_mcp_config(p)
    s = back.mcps[0]
    assert (s.id, s.transport, s.url, s.tools_prefix) == (
        "search",
        "http",
        "https://example.com/mcp",
        "mcp__search__",
    )
    assert s.auth.type == "bearer_env" and s.auth.env == "SEARCH_TOKEN"


def test_stdio_entry_survives_a_remote_write(tmp_path: Path) -> None:
    p = tmp_path / "mcp-config.yaml"
    p.write_text(
        "version: '1.0.0'\n"
        "mcps:\n"
        "  - id: local-fs\n"
        "    name: Local FS\n"
        "    transport: stdio\n"
        "    command: /bin/echo\n"
        "    tools_prefix: mcp__fs__\n"
        "    enabled: true\n"
        "    trust: trusted\n",
        encoding="utf-8",
    )
    cfg = load_mcp_config(p)
    cfg.mcps = [*cfg.mcps, _remote()]
    write_mcp_config(p, cfg)
    back = load_mcp_config(p)
    by_id = {s.id: s for s in back.mcps}
    assert set(by_id) == {"local-fs", "search"}
    # The hand-authored stdio server keeps its command (not stripped).
    assert by_id["local-fs"].transport == "stdio"
    assert by_id["local-fs"].command == "/bin/echo"
