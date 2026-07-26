"""WeCom assist — envelope crypto, callback routes, active-send client.

Everything offline: the crypto is verified by round trips plus an
independent signature recomputation (see ADR-0019 for why no pasted
official ciphertext), HTTP is MockTransport, and the chat core is faked.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.wecom import router as wecom_router
from opspilot.channels.wecom_app import WeComAppClient, WeComAppError
from opspilot.channels.wecom_crypto import WeComCrypto, WeComCryptoError

_TOKEN = "QDG6eK"
_AES_KEY = base64.b64encode(os.urandom(32)).decode("ascii").rstrip("=")
_CORP_ID = "ww5823bf96d3bd56c7"

_ENV = {
    "WECOM_CORP_ID": _CORP_ID,
    "WECOM_AGENT_ID": "1000002",
    "WECOM_APP_SECRET": "app-secret",
    "WECOM_CALLBACK_TOKEN": _TOKEN,
    "WECOM_ENCODING_AES_KEY": _AES_KEY,
}


def _crypto() -> WeComCrypto:
    return WeComCrypto(_TOKEN, _AES_KEY, _CORP_ID)


class TestCrypto:
    def test_round_trip(self) -> None:
        crypto = _crypto()
        assert crypto.decrypt(crypto.encrypt("hello 运维")) == "hello 运维"

    def test_signature_matches_independent_recomputation(self) -> None:
        crypto = _crypto()
        encrypt = crypto.encrypt("x")
        # Independent implementation of the documented algorithm.
        expected = hashlib.sha1(  # noqa: S324 — protocol-mandated
            "".join(sorted([_TOKEN, "1409659813", "1372623149", encrypt])).encode()
        ).hexdigest()
        assert crypto.signature("1409659813", "1372623149", encrypt) == expected
        crypto.verify(expected, "1409659813", "1372623149", encrypt)  # no raise

    def test_bad_signature_rejected(self) -> None:
        crypto = _crypto()
        with pytest.raises(WeComCryptoError, match="signature"):
            crypto.verify("0" * 40, "1", "2", crypto.encrypt("x"))

    def test_tampered_ciphertext_rejected(self) -> None:
        crypto = _crypto()
        blob = bytearray(base64.b64decode(crypto.encrypt("x")))
        # Corrupt the FIRST block: in CBC this garbles the whole second
        # plaintext block, including the 4-byte message-length field, so decode
        # deterministically fails. (Flipping only the last byte would just
        # mutate the PKCS#7 pad, which stays valid ~1/256 of the time — flaky.)
        blob[0] ^= 0xFF
        with pytest.raises(WeComCryptoError):
            crypto.decrypt(base64.b64encode(bytes(blob)).decode())

    def test_wrong_receive_id_rejected(self) -> None:
        other = WeComCrypto(_TOKEN, _AES_KEY, "ww-other-corp")
        with pytest.raises(WeComCryptoError, match="receive id"):
            _crypto().decrypt(other.encrypt("x"))

    def test_bad_key_length_rejected(self) -> None:
        with pytest.raises(WeComCryptoError, match="43"):
            WeComCrypto(_TOKEN, "short", _CORP_ID)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(wecom_router, prefix="/api")
    return app


def _signed_params(crypto: WeComCrypto, encrypt: str) -> dict[str, str]:
    ts, nonce = "1409659813", "1372623149"
    return {
        "msg_signature": crypto.signature(ts, nonce, encrypt),
        "timestamp": ts,
        "nonce": nonce,
    }


class TestCallbackRoutes:
    def test_unconfigured_404(self) -> None:
        with TestClient(_app()) as client:
            res = client.get(
                "/api/channels/wecom/callback",
                params={"msg_signature": "x", "timestamp": "1", "nonce": "2", "echostr": "e"},
            )
        assert res.status_code == 404

    def test_url_verification_echoes_decrypted(self) -> None:
        crypto = _crypto()
        echostr = crypto.encrypt("7818572891906148000")
        with patch.dict(os.environ, _ENV), TestClient(_app()) as client:
            res = client.get(
                "/api/channels/wecom/callback",
                params={**_signed_params(crypto, echostr), "echostr": echostr},
            )
        assert res.status_code == 200
        assert res.text == "7818572891906148000"

    def test_bad_signature_403(self) -> None:
        crypto = _crypto()
        echostr = crypto.encrypt("e")
        with patch.dict(os.environ, _ENV), TestClient(_app()) as client:
            res = client.get(
                "/api/channels/wecom/callback",
                params={
                    "msg_signature": "0" * 40,
                    "timestamp": "1",
                    "nonce": "2",
                    "echostr": echostr,
                },
            )
        assert res.status_code == 403

    def test_text_message_acknowledged_and_answered(self) -> None:
        crypto = _crypto()
        plain = (
            "<xml><ToUserName><![CDATA[ww]]></ToUserName>"
            "<FromUserName><![CDATA[vicente]]></FromUserName>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[VPN SOP?]]></Content></xml>"
        )
        encrypt = crypto.encrypt(plain)
        sent: list[tuple[str, str]] = []

        class FakeAppClient:
            def send_text(self, user: str, content: str) -> None:
                sent.append((user, content))

        app = _app()
        app.state.wecom_app = FakeAppClient()
        with (
            patch.dict(os.environ, _ENV),
            patch("opspilot.api.routes.wecom.answer_chat", return_value="Check the VPN runbook."),
            TestClient(app) as client,
        ):
            res = client.post(
                "/api/channels/wecom/callback",
                params=_signed_params(crypto, encrypt),
                content=f"<xml><Encrypt><![CDATA[{encrypt}]]></Encrypt></xml>",
            )
        assert res.status_code == 200
        assert res.text == "success"
        # TestClient runs background tasks before returning.
        assert sent == [("vicente", "Check the VPN runbook.")]

    def test_malformed_body_403(self) -> None:
        crypto = _crypto()
        with patch.dict(os.environ, _ENV), TestClient(_app()) as client:
            res = client.post(
                "/api/channels/wecom/callback",
                params=_signed_params(crypto, "not-the-signed-blob"),
                content="<xml><Encrypt>not-the-signed-blob</Encrypt></xml>",
            )
        assert res.status_code == 403


class TestAppClient:
    def _client(self, handler: Any) -> WeComAppClient:
        return WeComAppClient(
            _CORP_ID,
            1000002,
            "app-secret",
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    def test_token_fetched_once_and_send_payload(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path.endswith("/gettoken"):
                return httpx.Response(
                    200, json={"errcode": 0, "access_token": "tok-1", "expires_in": 7200}
                )
            body = json.loads(request.content)
            assert body["touser"] == "vicente"
            assert body["agentid"] == 1000002
            assert request.url.params["access_token"] == "tok-1"
            return httpx.Response(200, json={"errcode": 0})

        client = self._client(handler)
        client.send_text("vicente", "hi")
        client.send_text("vicente", "again")
        assert calls.count("/cgi-bin/gettoken") == 1  # cached

    def test_expired_token_refreshed_once(self) -> None:
        tokens = iter(["tok-old", "tok-new"])
        sends = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal sends
            if request.url.path.endswith("/gettoken"):
                return httpx.Response(
                    200, json={"errcode": 0, "access_token": next(tokens), "expires_in": 7200}
                )
            sends += 1
            if request.url.params["access_token"] == "tok-old":
                return httpx.Response(200, json={"errcode": 42001, "errmsg": "expired"})
            return httpx.Response(200, json={"errcode": 0})

        client = self._client(handler)
        client.send_text("vicente", "hi")
        assert sends == 2  # expired attempt + retry with fresh token

    def test_send_error_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/gettoken"):
                return httpx.Response(
                    200, json={"errcode": 0, "access_token": "t", "expires_in": 7200}
                )
            return httpx.Response(200, json={"errcode": 81013, "errmsg": "user not found"})

        with pytest.raises(WeComAppError, match="81013"):
            self._client(handler).send_text("ghost", "hi")

    def test_token_expiry_slack_respected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/gettoken"):
                return httpx.Response(
                    200, json={"errcode": 0, "access_token": "t", "expires_in": 7200}
                )
            return httpx.Response(200, json={"errcode": 0})

        client = self._client(handler)
        client.send_text("v", "x")
        # Cached expiry sits ~7080s out (7200 - 120 slack).
        assert client._token_expires_at - time.monotonic() == pytest.approx(7080, abs=5)
