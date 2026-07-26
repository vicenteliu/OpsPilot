"""Built-in minimal web search (#120)."""

from __future__ import annotations

from typing import Any

from opspilot.websearch import make_web_search_tool, web_search

_BRAVE = {
    "web": {
        "results": [
            {"title": "VPN", "url": "http://vpn", "description": "A VPN extends a network."},
            {"title": "Topic one", "url": "http://1", "description": "one"},
            {"title": "Topic two", "url": "http://2", "description": "two"},
        ]
    }
}


def _get(_q: str, _t: float) -> dict[str, Any]:
    return _BRAVE


def test_parses_brave_results() -> None:
    r = web_search("vpn", http_get=_get, max_results=5)
    assert r[0] == {"title": "VPN", "url": "http://vpn", "snippet": "A VPN extends a network."}
    assert [x["url"] for x in r] == ["http://vpn", "http://1", "http://2"]


def test_max_results_caps() -> None:
    data = {"web": {"results": [{"title": f"t{i}", "url": f"u{i}"} for i in range(10)]}}
    assert len(web_search("x", http_get=lambda q, t: data, max_results=3)) == 3


def test_empty_query_returns_empty() -> None:
    assert web_search("   ", http_get=_get) == []


def test_network_error_degrades_to_empty() -> None:
    def boom(_q: str, _t: float) -> dict[str, Any]:
        raise RuntimeError("network down")

    assert web_search("x", http_get=boom) == []


def test_tool_def_shape() -> None:
    tool, _handler = make_web_search_tool()
    assert tool.name == "web_search"
    assert tool.parameters["required"] == ["query"]
