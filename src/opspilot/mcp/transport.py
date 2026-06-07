"""MCP JSON-RPC 2.0 transport implementations.

Protocol reference: https://spec.modelcontextprotocol.io/specification/

Both transports implement the same interface:
  initialize() → dict
  list_tools() → list[dict]
  call_tool(name, arguments) → dict
  close() → None
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from typing import Any, Protocol, cast

import httpx

from ..errors import ProviderError

MCP_PROTOCOL_VERSION = "2024-11-05"
# Matches ${VAR} and ${VAR:-default} bash-style expansions.
_PLACEHOLDER_RE = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _resolve_env_value(value: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        var, default = m.group(1), m.group(2) or ""
        return os.environ.get(var, default)

    return _PLACEHOLDER_RE.sub(_sub, value)


class McpTransport(Protocol):
    def initialize(self) -> dict[str, Any]: ...
    def list_tools(self) -> list[dict[str, Any]]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def close(self) -> None: ...


class StdioTransport:
    """JSON-RPC 2.0 over subprocess stdin/stdout (line-delimited JSON)."""

    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None) -> None:
        merged_env = {**os.environ}
        if env:
            for k, v in env.items():
                merged_env[k] = _resolve_env_value(v)
        resolved_args = [_resolve_env_value(a) for a in args]

        self._proc = subprocess.Popen(
            [command, *resolved_args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()
        self._next_id = 1

    def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            msg_id = self._next_id
            self._next_id += 1
            payload: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
            if params is not None:
                payload["params"] = params
            line = json.dumps(payload) + "\n"
            assert self._proc.stdin
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
            assert self._proc.stdout
            resp_line = self._proc.stdout.readline()
        if not resp_line:
            raise ProviderError("MCP stdio server closed unexpectedly", error_code="mcp_closed")
        resp = json.loads(resp_line)
        if "error" in resp:
            raise ProviderError(
                f"MCP error {resp['error'].get('code')}: {resp['error'].get('message')}",
                error_code="mcp_rpc_error",
            )
        return cast("dict[str, Any]", resp.get("result", {}))

    def _notify(self, method: str) -> None:
        with self._lock:
            payload = {"jsonrpc": "2.0", "method": method}
            assert self._proc.stdin
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()

    def initialize(self) -> dict[str, Any]:
        result = self._send(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "opspilot", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._send("tools/list")
        return cast("list[dict[str, Any]]", result.get("tools", []))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._send("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self._proc.kill()


class HttpTransport:
    """JSON-RPC 2.0 over HTTP POST."""

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        resolved: dict[str, str] = {}
        if headers:
            for k, v in headers.items():
                resolved[k] = _resolve_env_value(v)
        self._url = url
        self._client = httpx.Client(headers=resolved, timeout=30)
        self._next_id = 1

    def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
        }
        self._next_id += 1
        if params is not None:
            payload["params"] = params
        try:
            resp = self._client.post(self._url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"MCP HTTP error: {exc}", error_code="mcp_http_error") from exc
        data = resp.json()
        if "error" in data:
            raise ProviderError(
                f"MCP error {data['error'].get('code')}: {data['error'].get('message')}",
                error_code="mcp_rpc_error",
            )
        return cast("dict[str, Any]", data.get("result", {}))

    def initialize(self) -> dict[str, Any]:
        return self._send(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "opspilot", "version": "0.1.0"},
            },
        )

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._send("tools/list")
        return cast("list[dict[str, Any]]", result.get("tools", []))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._send("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        self._client.close()
