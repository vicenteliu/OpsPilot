"""MCP API routes: GET /api/mcp/servers, GET /api/mcp/probe/{server_id}."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_DEFAULT_MCP_CONFIG = Path("mcp-config.yaml")


@router.get("/mcp/servers")
async def list_mcp_servers(request: Request) -> dict[str, Any]:
    """List all registered MCP servers from mcp-config.yaml."""
    from ...mcp import load_mcp_config, McpRegistry

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        if not _DEFAULT_MCP_CONFIG.exists():
            return {"servers": []}
        cfg = load_mcp_config(_DEFAULT_MCP_CONFIG)
        servers = [
            {
                "id": s.id,
                "name": s.name,
                "transport": s.transport,
                "enabled": s.enabled,
                "tools_prefix": s.tools_prefix,
                "trust": s.trust,
            }
            for s in cfg.mcps
        ]

        enabled = [s for s in cfg.mcps if s.enabled]
        tools_by_server: dict[str, list[dict[str, str]]] = {}
        if enabled:
            registry = McpRegistry.from_config(cfg)
            try:
                raw = registry.refresh_all_tools()
                for sid, tools in raw.items():
                    tools_by_server[sid] = [
                        {"name": t.name, "description": t.description}
                        for t in tools
                    ]
            except Exception:  # noqa: BLE001
                pass
            finally:
                registry.close_all()

        for s in servers:
            s["tools"] = tools_by_server.get(s["id"], [])

        return {"servers": servers}

    return await loop.run_in_executor(None, _run)


@router.get("/mcp/probe/{server_id}")
async def probe_mcp_server(server_id: str, request: Request) -> dict[str, Any]:
    """Probe a single MCP server for health and tool list."""
    from ...mcp import load_mcp_config
    from ...mcp.registry import McpServerClient

    loop = asyncio.get_event_loop()

    def _run() -> Any:
        if not _DEFAULT_MCP_CONFIG.exists():
            return None
        cfg = load_mcp_config(_DEFAULT_MCP_CONFIG)
        srv_cfg = next((s for s in cfg.mcps if s.id == server_id), None)
        if srv_cfg is None:
            return None

        client = McpServerClient(srv_cfg)
        try:
            tools = client.refresh_tools()
            return {
                "server_id": server_id,
                "online": True,
                "tools_count": len(tools),
                "tools": [{"name": t.name, "description": t.description} for t in tools],
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "server_id": server_id,
                "online": False,
                "tools_count": 0,
                "tools": [],
                "error": str(exc),
            }
        finally:
            client.close()

    result = await loop.run_in_executor(None, _run)
    if result is None:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found")
    return result
