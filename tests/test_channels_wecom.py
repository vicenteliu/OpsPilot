"""WeCom notify channel — markdown webhook, truncation, error surfacing.

All HTTP is faked with httpx.MockTransport; no live WeCom is contacted.
See docs/adr/0016 for the notify-mode decision.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from opspilot.channels.wecom import _MAX_MARKDOWN_BYTES, WeComNotifier, _truncate_markdown

_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key"


def _notifier(handler: Any) -> WeComNotifier:
    return WeComNotifier(_URL, http=httpx.Client(transport=httpx.MockTransport(handler)))


class TestWeComNotifier:
    def test_posts_markdown_with_key_and_body(self) -> None:
        sent: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            assert "key=test-key" in str(request.url)
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

        _notifier(handler).notify("IT-101", "## OpsPilot suggestion\nVPN down.")
        assert sent[0]["msgtype"] == "markdown"
        content = sent[0]["markdown"]["content"]
        assert content.startswith("**IT-101**\n")
        assert "VPN down." in content

    def test_wecom_errcode_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook url"})

        with pytest.raises(RuntimeError, match="93000"):
            _notifier(handler).notify("IT-101", "body")

    def test_http_error_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        with pytest.raises(httpx.HTTPStatusError):
            _notifier(handler).notify("IT-101", "body")


class TestTruncateMarkdown:
    def test_short_text_untouched(self) -> None:
        assert _truncate_markdown("short") == "short"

    def test_long_text_cut_on_utf8_boundary_within_limit(self) -> None:
        text = "运维" * 4096  # 3 bytes per char in UTF-8
        out = _truncate_markdown(text)
        raw = out.encode("utf-8")  # decodes cleanly = valid boundary
        assert len(raw) <= _MAX_MARKDOWN_BYTES
        assert out.endswith("…")
