"""OpsPilot MCP client — Model Context Protocol integration (PR-31).

Usage::

    from opspilot.mcp import McpRegistry, load_mcp_config

    cfg = load_mcp_config(Path("mcp-config.yaml"))
    registry = McpRegistry.from_config(cfg)
    registry.refresh_all_tools()
    result = registry.call_tool("mcp__fs__read_file", {"path": "/workspace/README.md"})
    print(result.text)
    registry.close_all()
"""

from .config_loader import load_mcp_config
from .registry import McpRegistry, McpServerClient
from .types import McpCallResult, McpConfig, McpServerConfig, McpToolInfo

__all__ = [
    "load_mcp_config",
    "McpRegistry",
    "McpServerClient",
    "McpCallResult",
    "McpConfig",
    "McpServerConfig",
    "McpToolInfo",
]
