"""WeCom callback envelope crypto (ADR-0019).

Implements the documented WXBizMsgCrypt algorithm used by every WeCom
self-built-app callback:

* ``msg_signature`` = sha1 of the four values ``token, timestamp, nonce,
  encrypt`` sorted lexicographically and concatenated.
* AES key = base64-decode(EncodingAESKey + ``"="``) → 32 bytes; AES-CBC
  with IV = key[:16].
* Plaintext layout = 16 random bytes ‖ 4-byte big-endian message length ‖
  message ‖ receive id (the corp id), PKCS#7-padded to 32-byte blocks.

Offline-verified by construction: encrypt→decrypt round trips and an
independent signature recomputation in the tests. Live verification
against a real WeCom enterprise is a documented post-deployment step.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_BLOCK = 32


class WeComCryptoError(Exception):
    """Signature mismatch, malformed envelope, or bad configuration."""


class WeComCrypto:
    """Signature check + AES envelope for one callback configuration."""

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str) -> None:
        if len(encoding_aes_key) != 43:
            raise WeComCryptoError("EncodingAESKey must be exactly 43 characters")
        self._token = token
        self._key = base64.b64decode(encoding_aes_key + "=")
        self._receive_id = receive_id

    # ── signature ──────────────────────────────────────────────────────

    def signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        raw = "".join(sorted([self._token, timestamp, nonce, encrypt]))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()  # noqa: S324 — protocol-mandated sha1

    def verify(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str) -> None:
        expected = self.signature(timestamp, nonce, encrypt)
        if not hmac.compare_digest(expected, msg_signature):
            raise WeComCryptoError("msg_signature mismatch")

    # ── envelope ───────────────────────────────────────────────────────

    def decrypt(self, encrypt_b64: str) -> str:
        try:
            data = base64.b64decode(encrypt_b64)
            decryptor = Cipher(algorithms.AES(self._key), modes.CBC(self._key[:16])).decryptor()
            plain = decryptor.update(data) + decryptor.finalize()
        except Exception as exc:  # noqa: BLE001 — uniform error surface
            raise WeComCryptoError("undecryptable envelope") from exc
        pad = plain[-1] if plain else 0
        if not 1 <= pad <= _BLOCK or len(plain) < 20 + pad:
            raise WeComCryptoError("bad padding")
        plain = plain[:-pad]
        (msg_len,) = struct.unpack(">I", plain[16:20])
        if 20 + msg_len > len(plain):
            raise WeComCryptoError("bad message length")
        receive_id = plain[20 + msg_len :].decode("utf-8", errors="replace")
        if receive_id != self._receive_id:
            raise WeComCryptoError("receive id mismatch")
        return plain[20 : 20 + msg_len].decode("utf-8")

    def encrypt(self, msg: str) -> str:
        payload = msg.encode("utf-8")
        raw = (
            os.urandom(16)
            + struct.pack(">I", len(payload))
            + payload
            + self._receive_id.encode("utf-8")
        )
        pad = _BLOCK - len(raw) % _BLOCK
        raw += bytes([pad]) * pad
        encryptor = Cipher(algorithms.AES(self._key), modes.CBC(self._key[:16])).encryptor()
        return base64.b64encode(encryptor.update(raw) + encryptor.finalize()).decode("ascii")
