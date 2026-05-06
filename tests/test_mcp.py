"""Tests for MCP client integration (PR-31).

No live MCP servers required — transport is mocked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from opspilot.errors import ConfigError
from opspilot.mcp.config_loader import load_mcp_config
from opspilot.mcp.registry import McpRegistry, McpServerClient
from opspilot.mcp.types import McpConfig, McpServerConfig

EXAMPLE_CONFIG = Path(__file__).parents[1] / "examples" / "mcp_config" / "mcp-config.yaml"


# ── Config loading ────────────────────────────────────────────────────────


def test_config_loads_example():
    cfg = load_mcp_config(EXAMPLE_CONFIG)
    assert cfg.version == "1.0.0"
    assert len(cfg.mcps) == 2


def test_config_has_fs_readonly():
    cfg = load_mcp_config(EXAMPLE_CONFIG)
    ids = [s.id for s in cfg.mcps]
    assert "fs-readonly" in ids


def test_config_notion_disabled():
    cfg = load_mcp_config(EXAMPLE_CONFIG)
    notion = next(s for s in cfg.mcps if s.id == "notion-main")
    assert not notion.enabled


def test_config_rejects_inline_secret(tmp_path: Path):
    bad_yaml = """
version: "1.0.0"
mcps:
  - id: "bad-server"
    name: "Bad"
    transport: "stdio"
    command: "npx"
    args: []
    env:
      NOTION_TOKEN: "sk-realTokenABCDEF1234567890"
    tools_prefix: "mcp__bad__"
    enabled: true
    trust: "unknown"
    auth:
      type: "none"
"""
    p = tmp_path / "mcp-config.yaml"
    p.write_text(bad_yaml)
    with pytest.raises(ConfigError, match="inline secret"):
        load_mcp_config(p)


def test_config_allows_placeholder_env(tmp_path: Path):
    ok_yaml = """
version: "1.0.0"
mcps:
  - id: "ok-server"
    name: "OK"
    transport: "stdio"
    command: "npx"
    args: []
    env:
      NOTION_TOKEN: "${NOTION_API_KEY}"
    tools_prefix: "mcp__ok__"
    enabled: true
    trust: "trusted"
    auth:
      type: "none"
"""
    p = tmp_path / "mcp-config.yaml"
    p.write_text(ok_yaml)
    cfg = load_mcp_config(p)
    assert cfg.mcps[0].id == "ok-server"


# ── Tool filtering ────────────────────────────────────────────────────────


def _make_server_cfg(**kwargs: Any) -> McpServerConfig:
    defaults = dict(
        id="test",
        name="Test",
        transport="stdio",
        command="echo",
        args=[],
        tools_prefix="mcp__test__",
        enabled=True,
        trust="trusted",
    )
    defaults.update(kwargs)
    return McpServerConfig(**defaults)


def _mock_client(cfg: McpServerConfig, raw_tools: list[dict]) -> McpServerClient:
    client = McpServerClient(cfg)
    mock_transport = MagicMock()
    mock_transport.initialize.return_value = {}
    mock_transport.list_tools.return_value = raw_tools
    client._transport = mock_transport  # type: ignore[assignment]
    return client


def test_allowlist_filters_tools():
    cfg = _make_server_cfg(tools_allowlist=["read_file"])
    raw = [
        {"name": "read_file", "description": "read"},
        {"name": "write_file", "description": "write"},
    ]
    client = _mock_client(cfg, raw)
    tools = client.refresh_tools()
    assert len(tools) == 1
    assert tools[0].name == "read_file"


def test_denylist_filters_tools():
    cfg = _make_server_cfg(tools_denylist=["delete_page"])
    raw = [
        {"name": "create_page", "description": "create"},
        {"name": "delete_page", "description": "delete"},
    ]
    client = _mock_client(cfg, raw)
    tools = client.refresh_tools()
    assert len(tools) == 1
    assert tools[0].name == "create_page"


def test_no_filter_exposes_all_tools():
    cfg = _make_server_cfg()
    raw = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    client = _mock_client(cfg, raw)
    tools = client.refresh_tools()
    assert len(tools) == 3


# ── Registry routing ──────────────────────────────────────────────────────


def test_registry_routes_prefixed_call():
    cfg = _make_server_cfg(id="fs", tools_prefix="mcp__fs__")
    raw = [{"name": "read_file", "description": "read"}]
    client = _mock_client(cfg, raw)
    client.refresh_tools()
    client._transport.call_tool.return_value = {
        "content": [{"type": "text", "text": "hello"}],
        "isError": False,
    }

    registry = McpRegistry([client])
    result = registry.call_tool("mcp__fs__read_file", {"path": "/foo"})
    assert result.text == "hello"
    assert not result.is_error


def test_registry_raises_for_unknown_prefix():
    registry = McpRegistry([])
    with pytest.raises(ConfigError, match="No enabled MCP server"):
        registry.call_tool("mcp__unknown__do_thing", {})


def test_registry_only_loads_enabled():
    cfg = load_mcp_config(EXAMPLE_CONFIG)
    registry = McpRegistry.from_config(cfg)
    # Only fs-readonly is enabled; notion-main is disabled
    assert len(registry.list_servers()) == 1
    assert registry.list_servers()[0].id == "fs-readonly"


# ── Transport JSON-RPC shape ──────────────────────────────────────────────


def test_http_transport_posts_jsonrpc(respx_mock=None):
    import json
    import unittest.mock as mock

    from opspilot.mcp.transport import HttpTransport

    with mock.patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "search", "description": "search"}]},
        }
        mock_post.return_value = mock_response

        transport = HttpTransport(url="https://example.com/mcp")
        tools = transport.list_tools()

    assert len(tools) == 1
    assert tools[0]["name"] == "search"
    call_kwargs = mock_post.call_args
    payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
    assert payload["method"] == "tools/list"
    assert payload["jsonrpc"] == "2.0"
