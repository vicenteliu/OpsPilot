"""Tests for mcp/registry.py — McpServerClient and McpRegistry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from opspilot.errors import ConfigError
from opspilot.mcp.registry import McpRegistry, McpServerClient
from opspilot.mcp.types import McpCallResult, McpConfig, McpContent, McpServerConfig


# ── helpers ───────────────────────────────────────────────────────────────


def _cfg(
    server_id: str = "fs",
    transport: str = "stdio",
    command: str = "mcp-server",
    url: str | None = None,
    tools_allowlist: list[str] | None = None,
    tools_denylist: list[str] | None = None,
    enabled: bool = True,
) -> McpServerConfig:
    return McpServerConfig(
        id=server_id,
        name=server_id,
        transport=transport,
        command=command,
        url=url,
        tools_prefix=f"mcp__{server_id}__",
        tools_allowlist=tools_allowlist,
        tools_denylist=tools_denylist,
        enabled=enabled,
    )


def _mock_transport(tools: list[dict] | None = None):
    t = MagicMock()
    t.initialize.return_value = {}
    t.list_tools.return_value = tools or [{"name": "read_file", "description": "reads", "inputSchema": {}}]
    t.call_tool.return_value = {"content": [{"type": "text", "text": "result"}]}
    return t


# ── McpServerClient.connect ───────────────────────────────────────────────


def test_connect_stdio_creates_stdio_transport():
    cfg = _cfg(transport="stdio", command="mcp-fs")
    client = McpServerClient(cfg)
    mock_t = _mock_transport()
    with patch("opspilot.mcp.registry.StdioTransport", return_value=mock_t):
        client.connect()
    mock_t.initialize.assert_called_once()
    assert client._transport is mock_t


def test_connect_http_creates_http_transport():
    cfg = _cfg(transport="http", url="http://localhost:3000/rpc")
    client = McpServerClient(cfg)
    mock_t = _mock_transport()
    with patch("opspilot.mcp.registry.HttpTransport", return_value=mock_t):
        client.connect()
    mock_t.initialize.assert_called_once()


def test_connect_stdio_missing_command_raises():
    cfg = McpServerConfig(id="x", name="x", transport="stdio", tools_prefix="mcp__x__")
    client = McpServerClient(cfg)
    with pytest.raises(ConfigError, match="command"):
        client.connect()


def test_connect_http_missing_url_raises():
    cfg = McpServerConfig(id="x", name="x", transport="http", tools_prefix="mcp__x__")
    client = McpServerClient(cfg)
    with pytest.raises(ConfigError, match="url"):
        client.connect()


# ── McpServerClient.refresh_tools ────────────────────────────────────────


def test_refresh_tools_returns_tool_list():
    cfg = _cfg()
    client = McpServerClient(cfg)
    client._transport = _mock_transport([{"name": "read_file", "description": "reads", "inputSchema": {}}])
    tools = client.refresh_tools()
    assert len(tools) == 1
    assert tools[0].name == "read_file"


def test_refresh_tools_connects_if_no_transport():
    cfg = _cfg()
    client = McpServerClient(cfg)
    mock_t = _mock_transport()
    with patch("opspilot.mcp.registry.StdioTransport", return_value=mock_t):
        tools = client.refresh_tools()
    assert len(tools) == 1


def test_refresh_tools_applies_allowlist():
    cfg = _cfg(tools_allowlist=["read_file"])
    client = McpServerClient(cfg)
    client._transport = _mock_transport([
        {"name": "read_file", "description": "r", "inputSchema": {}},
        {"name": "write_file", "description": "w", "inputSchema": {}},
    ])
    tools = client.refresh_tools()
    assert len(tools) == 1
    assert tools[0].name == "read_file"


def test_refresh_tools_applies_denylist():
    cfg = _cfg(tools_denylist=["write_file"])
    client = McpServerClient(cfg)
    client._transport = _mock_transport([
        {"name": "read_file", "description": "r", "inputSchema": {}},
        {"name": "write_file", "description": "w", "inputSchema": {}},
    ])
    tools = client.refresh_tools()
    assert len(tools) == 1
    assert tools[0].name == "read_file"


# ── McpServerClient.call ─────────────────────────────────────────────────


def test_call_returns_result():
    cfg = _cfg()
    client = McpServerClient(cfg)
    client._transport = _mock_transport()
    result = client.call("read_file", {"path": "/tmp/x"})
    assert isinstance(result, McpCallResult)
    assert result.content[0].text == "result"


def test_call_blocked_by_denylist_raises():
    cfg = _cfg(tools_denylist=["write_file"])
    client = McpServerClient(cfg)
    client._transport = _mock_transport()
    with pytest.raises(ConfigError, match="not allowed"):
        client.call("write_file", {})


def test_call_connects_if_no_transport():
    cfg = _cfg()
    client = McpServerClient(cfg)
    mock_t = _mock_transport()
    with patch("opspilot.mcp.registry.StdioTransport", return_value=mock_t):
        result = client.call("read_file", {})
    assert result.content[0].text == "result"


# ── McpServerClient.as_tool_defs ─────────────────────────────────────────


def test_as_tool_defs_uses_prefix():
    cfg = _cfg(server_id="fs")
    client = McpServerClient(cfg)
    client._transport = _mock_transport()
    client.refresh_tools()
    defs = client.as_tool_defs()
    assert len(defs) == 1
    assert defs[0].name == "mcp__fs__read_file"


def test_as_tool_defs_empty_before_refresh():
    cfg = _cfg()
    client = McpServerClient(cfg)
    assert client.as_tool_defs() == []


# ── McpServerClient.close ────────────────────────────────────────────────


def test_close_calls_transport_close():
    cfg = _cfg()
    client = McpServerClient(cfg)
    mock_t = _mock_transport()
    client._transport = mock_t
    client.close()
    mock_t.close.assert_called_once()
    assert client._transport is None


def test_close_noop_if_no_transport():
    cfg = _cfg()
    client = McpServerClient(cfg)
    client.close()  # must not raise


# ── McpRegistry ───────────────────────────────────────────────────────────


def _make_registry(server_ids: list[str], tools_per_server: int = 1) -> McpRegistry:
    clients = []
    for sid in server_ids:
        cfg = _cfg(server_id=sid)
        c = McpServerClient(cfg)
        c._transport = _mock_transport(
            [{"name": f"tool_{i}", "description": "", "inputSchema": {}} for i in range(tools_per_server)]
        )
        c.refresh_tools()
        clients.append(c)
    return McpRegistry(clients)


def test_registry_from_config_skips_disabled():
    cfg = McpConfig(version="1", mcps=[
        _cfg(server_id="enabled", enabled=True),
        _cfg(server_id="disabled", enabled=False),
    ])
    reg = McpRegistry.from_config(cfg)
    ids = [c.cfg.id for c in reg._clients.values()]
    assert "enabled" in ids
    assert "disabled" not in ids


def test_registry_list_servers():
    reg = _make_registry(["a", "b"])
    servers = reg.list_servers()
    assert len(servers) == 2


def test_registry_as_tool_defs_aggregates():
    reg = _make_registry(["a", "b"], tools_per_server=2)
    defs = reg.as_tool_defs()
    assert len(defs) == 4


def test_registry_call_tool_routes_by_prefix():
    reg = _make_registry(["fs"])
    result = reg.call_tool("mcp__fs__tool_0", {})
    assert isinstance(result, McpCallResult)


def test_registry_call_tool_unknown_prefix_raises():
    reg = _make_registry(["fs"])
    with pytest.raises(ConfigError, match="No enabled MCP server"):
        reg.call_tool("mcp__unknown__tool", {})


def test_registry_close_all():
    reg = _make_registry(["a", "b"])
    for c in reg._clients.values():
        c._transport = _mock_transport()
    reg.close_all()
    for c in reg._clients.values():
        assert c._transport is None


def test_registry_refresh_all_tools():
    reg = _make_registry(["a"])
    for c in reg._clients.values():
        c._transport = _mock_transport()
    result = reg.refresh_all_tools()
    assert "a" in result
