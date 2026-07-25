"""WeCom Channel — notify mode over the group-robot webhook (ADR-0016).

Outbound-only: the group robot can post into one group but cannot receive
messages (WeCom has no long-polling API; receiving would require a public
HTTPS callback with an AES handshake). The notifier pushes intake
suggestions as WeCom markdown messages; assist mode is a separate, future
decision recorded in the ADR.
"""

from __future__ import annotations

import httpx

# WeCom hard limit for a markdown message's content, in UTF-8 bytes.
_MAX_MARKDOWN_BYTES = 4096


def _truncate_markdown(text: str) -> str:
    """Cut to the WeCom byte limit on a UTF-8 boundary, marking the cut."""
    raw = text.encode("utf-8")
    if len(raw) <= _MAX_MARKDOWN_BYTES:
        return text
    ellipsis = "\n…"
    cut = raw[: _MAX_MARKDOWN_BYTES - len(ellipsis.encode("utf-8"))]
    return cut.decode("utf-8", errors="ignore") + ellipsis


class WeComNotifier:
    """Posts one markdown message per delivered suggestion to a WeCom group.

    The webhook URL embeds the robot's secret key — read it from
    ``WECOM_WEBHOOK_URL``, never a CLI argument.
    """

    def __init__(self, webhook_url: str, http: httpx.Client | None = None) -> None:
        self._url = webhook_url
        self._http = http or httpx.Client(timeout=15.0)

    def notify(self, key: str, body: str) -> None:
        content = _truncate_markdown(f"**{key}**\n{body}")
        res = self._http.post(
            self._url, json={"msgtype": "markdown", "markdown": {"content": content}}
        )
        res.raise_for_status()
        payload = res.json()
        if payload.get("errcode", 0) != 0:
            raise RuntimeError(
                f"WeCom webhook error {payload.get('errcode')}: {payload.get('errmsg')}"
            )
