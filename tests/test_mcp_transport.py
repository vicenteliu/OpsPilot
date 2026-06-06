"""Tests for mcp/transport.py — StdioTransport, HttpTransport, _resolve_env_value."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from opspilot.errors import ProviderError
from opspilot.mcp.transport import (
    HttpTransport,
    StdioTransport,
    _resolve_env_value,
)

# ── _resolve_env_value ────────────────────────────────────────────────────


def test_resolve_env_value_replaces_placeholder(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "secret123")
    assert _resolve_env_value("${MY_TOKEN}") == "secret123"


def test_resolve_env_value_no_placeholder():
    assert _resolve_env_value("plain-string") == "plain-string"


def test_resolve_env_value_missing_var(monkeypatch):
    monkeypatch.delenv("MISSING_VAR_XYZ", raising=False)
    assert _resolve_env_value("${MISSING_VAR_XYZ}") == ""


def test_resolve_env_value_multiple_placeholders(monkeypatch):
    monkeypatch.setenv("A", "hello")
    monkeypatch.setenv("B", "world")
    assert _resolve_env_value("${A}-${B}") == "hello-world"


# ── StdioTransport (mock subprocess) ─────────────────────────────────────


def _make_proc(responses: list[str]):
    """Fake subprocess.Popen that returns pre-canned JSON-RPC responses."""
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    # Non-empty strings get a newline; empty string means EOF (readline returns "")
    proc.stdout.readline.side_effect = [r if r == "" else r + "\n" for r in responses]
    return proc


def _json_ok(result: dict, id: int = 1) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id, "result": result})


def _json_err(code: int, msg: str, id: int = 1) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": msg}})


@pytest.fixture()
def stdio_transport(monkeypatch):
    """Returns a StdioTransport whose subprocess is fully mocked."""
    proc = _make_proc([])
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc):
        t = StdioTransport("echo", [])
    t._proc = proc
    return t, proc


def test_stdio_initialize_sends_method(monkeypatch):
    init_resp = _json_ok({"protocolVersion": "2024-11-05"}, id=1)
    proc = _make_proc([init_resp])
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc):
        t = StdioTransport("echo", [])
    t._proc = proc
    result = t.initialize()
    assert result["protocolVersion"] == "2024-11-05"


def test_stdio_list_tools(monkeypatch):
    tools_resp = _json_ok(
        {"tools": [{"name": "read_file", "description": "reads", "inputSchema": {}}]}, id=1
    )
    proc = _make_proc([tools_resp])
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc):
        t = StdioTransport("echo", [])
    t._proc = proc
    tools = t.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "read_file"


def test_stdio_list_tools_empty(monkeypatch):
    resp = _json_ok({}, id=1)
    proc = _make_proc([resp])
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc):
        t = StdioTransport("echo", [])
    t._proc = proc
    assert t.list_tools() == []


def test_stdio_call_tool(monkeypatch):
    resp = _json_ok({"content": [{"type": "text", "text": "file content"}]}, id=1)
    proc = _make_proc([resp])
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc):
        t = StdioTransport("echo", [])
    t._proc = proc
    result = t.call_tool("read_file", {"path": "/tmp/x"})
    assert result["content"][0]["text"] == "file content"


def test_stdio_send_raises_on_empty_response(monkeypatch):
    proc = _make_proc([""])  # empty line → EOF
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc):
        t = StdioTransport("echo", [])
    t._proc = proc
    with pytest.raises(ProviderError, match="closed unexpectedly"):
        t._send("tools/list")


def test_stdio_send_raises_on_rpc_error(monkeypatch):
    resp = _json_err(-32601, "Method not found", id=1)
    proc = _make_proc([resp])
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc):
        t = StdioTransport("echo", [])
    t._proc = proc
    with pytest.raises(ProviderError, match="MCP error"):
        t._send("tools/list")


def test_stdio_close(monkeypatch):
    proc = _make_proc([])
    proc.wait = MagicMock()
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc):
        t = StdioTransport("echo", [])
    t._proc = proc
    t.close()
    proc.stdin.close.assert_called_once()
    proc.wait.assert_called_once()


def test_stdio_close_kills_on_timeout(monkeypatch):
    proc = _make_proc([])
    proc.wait = MagicMock(side_effect=Exception("timeout"))
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc):
        t = StdioTransport("echo", [])
    t._proc = proc
    t.close()  # must not raise
    proc.kill.assert_called_once()


def test_stdio_env_resolution(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "resolved_val")
    proc = _make_proc([])
    with patch("opspilot.mcp.transport.subprocess.Popen", return_value=proc) as mock_popen:
        StdioTransport("echo", [], env={"API_KEY": "${TEST_KEY}"})
    call_kwargs = mock_popen.call_args[1]
    assert call_kwargs["env"]["API_KEY"] == "resolved_val"


# ── HttpTransport (mock httpx) ────────────────────────────────────────────


def _http_transport(responses: list[dict]) -> HttpTransport:
    """Returns an HttpTransport whose httpx.Client is mocked."""
    mock_client = MagicMock()
    mock_client.post.side_effect = [_mock_response(r) for r in responses]
    with patch("opspilot.mcp.transport.httpx.Client", return_value=mock_client):
        t = HttpTransport("http://localhost:3000/rpc")
    t._client = mock_client
    return t


def _mock_response(data: dict):
    resp = MagicMock()
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


def test_http_initialize():
    t = _http_transport([{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}])
    result = t.initialize()
    assert result["protocolVersion"] == "2024-11-05"


def test_http_list_tools():
    t = _http_transport([{"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "search"}]}}])
    tools = t.list_tools()
    assert tools[0]["name"] == "search"


def test_http_list_tools_empty():
    t = _http_transport([{"jsonrpc": "2.0", "id": 1, "result": {}}])
    assert t.list_tools() == []


def test_http_call_tool():
    t = _http_transport(
        [{"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ok"}]}}]
    )
    result = t.call_tool("search", {"query": "foo"})
    assert result["content"][0]["text"] == "ok"


def test_http_raises_on_rpc_error():
    t = _http_transport(
        [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid Request"}}]
    )
    with pytest.raises(ProviderError, match="MCP error"):
        t.initialize()


def test_http_raises_on_http_error():
    import httpx

    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.HTTPError("connection refused")
    with patch("opspilot.mcp.transport.httpx.Client", return_value=mock_client):
        t = HttpTransport("http://localhost:3000/rpc")
    with pytest.raises(ProviderError, match="MCP HTTP error"):
        t.initialize()


def test_http_close():
    t = _http_transport([])
    t.close()
    t._client.close.assert_called_once()


def test_http_header_resolution(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "token_abc")
    mock_client = MagicMock()
    with patch("opspilot.mcp.transport.httpx.Client", return_value=mock_client) as mock_cls:
        HttpTransport("http://localhost/rpc", headers={"Authorization": "Bearer ${NOTION_TOKEN}"})
    call_kwargs = mock_cls.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Bearer token_abc"
