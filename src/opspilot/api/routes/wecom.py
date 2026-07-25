"""WeCom assist callback — self-built-app rider on the API server (ADR-0019).

WeCom has no long-polling API: receiving messages requires this public
HTTPS callback (deploy behind ADR-0011 remote access). The POST handler
acknowledges immediately and answers through the active send API — same
accept-async stance as webhook intake (ADR-0015) — because a KB chat
takes far longer than WeCom's passive-reply window.

Configuration is environment-only; with any variable missing the routes
answer 404 and the server is otherwise unchanged (fail-closed).
"""

from __future__ import annotations

import asyncio
import logging
import os
import xml.etree.ElementTree as ET  # noqa: S405 — payloads are signature-verified + decrypted first
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ...channels.wecom_app import WeComAppClient
from ...channels.wecom_crypto import WeComCrypto, WeComCryptoError
from .chat import answer_chat

logger = logging.getLogger("opspilot.api.wecom")

router = APIRouter()


@dataclass(frozen=True)
class _AssistConfig:
    corp_id: str
    agent_id: int
    secret: str
    token: str
    encoding_aes_key: str


def _load_config() -> _AssistConfig | None:
    """Env-only configuration; None (→ 404) when any variable is missing."""
    corp_id = os.environ.get("WECOM_CORP_ID", "")
    agent_id = os.environ.get("WECOM_AGENT_ID", "")
    secret = os.environ.get("WECOM_APP_SECRET", "")
    token = os.environ.get("WECOM_CALLBACK_TOKEN", "")
    aes_key = os.environ.get("WECOM_ENCODING_AES_KEY", "")
    if not all([corp_id, agent_id, secret, token, aes_key]):
        return None
    return _AssistConfig(corp_id, int(agent_id), secret, token, aes_key)


def _crypto(cfg: _AssistConfig) -> WeComCrypto:
    return WeComCrypto(cfg.token, cfg.encoding_aes_key, cfg.corp_id)


def _require_config() -> _AssistConfig:
    cfg = _load_config()
    if cfg is None:
        raise HTTPException(status_code=404, detail="WeCom assist is not configured")
    return cfg


@router.get("/channels/wecom/callback")
def wecom_verify(msg_signature: str, timestamp: str, nonce: str, echostr: str) -> PlainTextResponse:
    """URL-verification handshake: echo the decrypted echostr."""
    cfg = _require_config()
    crypto = _crypto(cfg)
    try:
        crypto.verify(msg_signature, timestamp, nonce, echostr)
        return PlainTextResponse(crypto.decrypt(echostr))
    except WeComCryptoError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


async def _answer_and_send(request: Request, cfg: _AssistConfig, user: str, content: str) -> None:
    """Background: KB chat, then active send — never raises into the server."""
    try:
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None,
            lambda: answer_chat(request.app.state, [{"role": "user", "content": content}]),
        )
        client: WeComAppClient = getattr(request.app.state, "wecom_app", None) or WeComAppClient(
            cfg.corp_id, cfg.agent_id, cfg.secret
        )
        request.app.state.wecom_app = client  # reuse the token cache across messages
        await loop.run_in_executor(None, lambda: client.send_text(user, answer))
        logger.info("wecom assist answered %s", user)
    except Exception:  # noqa: BLE001 — callback path must never crash the server
        logger.exception("wecom assist failed for %s", user)


@router.post("/channels/wecom/callback")
async def wecom_message(
    request: Request,
    background: BackgroundTasks,
    msg_signature: str,
    timestamp: str,
    nonce: str,
) -> PlainTextResponse:
    """Inbound message: verify, decrypt, acknowledge, answer asynchronously."""
    cfg = _require_config()
    crypto = _crypto(cfg)
    body = await request.body()
    try:
        envelope = ET.fromstring(body.decode("utf-8"))  # noqa: S314 — verified + decrypted below
        encrypt = envelope.findtext("Encrypt") or ""
        crypto.verify(msg_signature, timestamp, nonce, encrypt)
        plain = crypto.decrypt(encrypt)
        msg = ET.fromstring(plain)  # noqa: S314 — authenticated content
    except (WeComCryptoError, ET.ParseError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if (msg.findtext("MsgType") or "") == "text":
        user = msg.findtext("FromUserName") or ""
        content = (msg.findtext("Content") or "").strip()
        if user and content:
            background.add_task(_answer_and_send, request, cfg, user, content)
    # Acknowledge immediately; the answer arrives via active send.
    return PlainTextResponse("success")
