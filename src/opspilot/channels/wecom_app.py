"""WeCom self-built-app client — active message send (ADR-0019).

Passive callback replies must return within seconds, but a KB chat takes
tens of seconds — so the callback acknowledges immediately and the answer
goes out through the active send API, mirroring the ADR-0015
accept-async pattern. The access token is cached until shortly before
its expiry and refreshed once on an expired-token error code.
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger("opspilot.channels.wecom_app")

_API = "https://qyapi.weixin.qq.com/cgi-bin"
# Refresh this many seconds before the advertised expiry.
_EXPIRY_SLACK_S = 120
# WeCom error codes meaning "access token invalid/expired" → refresh + retry once.
_TOKEN_ERRCODES = frozenset({40014, 42001})


class WeComAppError(Exception):
    """gettoken or message send failed."""


class WeComAppClient:
    """Minimal client for the two APIs assist mode needs: token + send."""

    def __init__(
        self,
        corp_id: str,
        agent_id: int,
        secret: str,
        http: httpx.Client | None = None,
    ) -> None:
        self._corp_id = corp_id
        self._agent_id = agent_id
        self._secret = secret
        self._http = http or httpx.Client(timeout=15.0)
        self._token = ""
        self._token_expires_at = 0.0

    def _fetch_token(self) -> str:
        res = self._http.get(
            f"{_API}/gettoken", params={"corpid": self._corp_id, "corpsecret": self._secret}
        )
        res.raise_for_status()
        payload = res.json()
        if payload.get("errcode", 0) != 0:
            raise WeComAppError(
                f"gettoken failed: {payload.get('errcode')} {payload.get('errmsg')}"
            )
        self._token = str(payload["access_token"])
        self._token_expires_at = (
            time.monotonic() + float(payload.get("expires_in", 7200)) - _EXPIRY_SLACK_S
        )
        return self._token

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        return self._fetch_token()

    def send_text(self, user: str, content: str) -> None:
        """Send one text message to a member; refresh the token once if expired."""
        body = {
            "touser": user,
            "msgtype": "text",
            "agentid": self._agent_id,
            "text": {"content": content},
        }
        payload = self._post_send(body)
        if payload.get("errcode", 0) in _TOKEN_ERRCODES:
            self._fetch_token()
            payload = self._post_send(body)
        if payload.get("errcode", 0) != 0:
            raise WeComAppError(f"send failed: {payload.get('errcode')} {payload.get('errmsg')}")

    def _post_send(self, body: dict[str, object]) -> dict[str, object]:
        res = self._http.post(
            f"{_API}/message/send", params={"access_token": self._access_token()}, json=body
        )
        res.raise_for_status()
        return dict(res.json())
