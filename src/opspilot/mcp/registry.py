"""McpRegistry — manages MCP servers from a config, routes tool calls by prefix."""

from __future__ import annotations

from typing import Any

from ..errors import ConfigError
from ..providers.types import ToolDef
from .transport import HttpTransport, StdioTransport
from .types import McpCallResult, McpConfig, McpContent, McpServerConfig, McpToolInfo


class McpServerClient:
    """Wraps one MCP server: holds its config + transport, applies tool filters."""

    def __init__(self, cfg: McpServerConfig) -> None:
        self.cfg = cfg
        self._transport: StdioTransport | HttpTransport | None = None
        self._tools: list[McpToolInfo] = []

    def connect(self) -> None:
        if self.cfg.transport == "stdio":
            if not self.cfg.command:
                raise ConfigError(f"MCP server '{self.cfg.id}': stdio transport requires command")
            self._transport = StdioTransport(
                command=self.cfg.command,
                args=self.cfg.args,
                env=self.cfg.env or {},
            )
        else:
            if not self.cfg.url:
                raise ConfigError(f"MCP server '{self.cfg.id}': http/sse transport requires url")
            self._transport = HttpTransport(
                url=self.cfg.url,
                headers=self.cfg.headers or {},
            )
        self._transport.initialize()

    def refresh_tools(self) -> list[McpToolInfo]:
        if self._transport is None:
            self.connect()
        assert self._transport
        raw = self._transport.list_tools()
        tools = [
            McpToolInfo(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_id=self.cfg.id,
            )
            for t in raw
        ]
        self._tools = [t for t in tools if self._allowed(t.name)]
        return self._tools

    def _allowed(self, tool_name: str) -> bool:
        if self.cfg.tools_allowlist is not None and tool_name not in self.cfg.tools_allowlist:
            return False
        return not (self.cfg.tools_denylist and tool_name in self.cfg.tools_denylist)

    def call(self, tool_name: str, arguments: dict[str, Any]) -> McpCallResult:
        if not self._allowed(tool_name):
            raise ConfigError(f"Tool '{tool_name}' is not allowed on server '{self.cfg.id}'")
        if self._transport is None:
            self.connect()
        assert self._transport
        raw = self._transport.call_tool(tool_name, arguments)
        content = [McpContent(**c) for c in raw.get("content", [])]
        return McpCallResult(content=content, is_error=raw.get("isError", False))

    def close(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None

    @property
    def prefixed_tools(self) -> list[McpToolInfo]:
        return self._tools

    def as_tool_defs(self) -> list[ToolDef]:
        prefix = self.cfg.tools_prefix
        return [
            ToolDef(
                name=f"{prefix}{t.name}",
                description=t.description,
                parameters=t.input_schema,
            )
            for t in self._tools
        ]


class McpRegistry:
    """Routes prefixed tool calls to the correct MCP server."""

    def __init__(self, clients: list[McpServerClient]) -> None:
        self._clients: dict[str, McpServerClient] = {c.cfg.id: c for c in clients}

    @classmethod
    def from_config(cls, cfg: McpConfig) -> McpRegistry:
        clients = [McpServerClient(srv) for srv in cfg.mcps if srv.enabled]
        return cls(clients)

    def list_servers(self) -> list[McpServerConfig]:
        return [c.cfg for c in self._clients.values()]

    def refresh_all_tools(self) -> dict[str, list[McpToolInfo]]:
        result: dict[str, list[McpToolInfo]] = {}
        for client in self._clients.values():
            result[client.cfg.id] = client.refresh_tools()
        return result

    def as_tool_defs(self) -> list[ToolDef]:
        defs: list[ToolDef] = []
        for client in self._clients.values():
            defs.extend(client.as_tool_defs())
        return defs

    def call_tool(self, prefixed_name: str, arguments: dict[str, Any]) -> McpCallResult:
        """Route a call like 'mcp__fs__read_file' to the correct server."""
        for client in self._clients.values():
            prefix = client.cfg.tools_prefix
            if prefixed_name.startswith(prefix):
                tool_name = prefixed_name[len(prefix) :]
                return client.call(tool_name, arguments)
        raise ConfigError(
            f"No enabled MCP server found for tool '{prefixed_name}'",
        )

    def close_all(self) -> None:
        for client in self._clients.values():
            client.close()
