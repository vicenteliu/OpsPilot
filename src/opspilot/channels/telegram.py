"""Telegram Channel adapter — assist mode over long polling (ADR-0012).

The bot makes outbound calls only (``getUpdates`` long poll + ``sendMessage``),
so it runs from behind any NAT with zero inbound exposure. Every message is
gated by an explicit chat-id allowlist; messages from unknown chats are
logged and dropped without a reply (no oracle for probers).

The channel doubles as a Source (ADR-0014): ``/intake``, ``/incident`` and
``/request`` file the message as a Work item and reply with the suggestion.
Intake rides this adapter because Telegram allows only one ``getUpdates``
poller per bot token — a separate source process would steal updates.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..intake import OpsPilotRunClient, render_comment
from .base import OpsPilotChatClient

logger = logging.getLogger("opspilot.channels.telegram")

# Telegram hard limit per sendMessage call.
_MAX_MESSAGE_CHARS = 4096
# Rolling per-chat context kept in memory (user+assistant turns).
_MAX_HISTORY_MESSAGES = 20

_GREETING = (
    "OpsPilot assist channel connected. Ask an IT question and I will "
    "answer from the knowledge base. Send /reset to clear the conversation.\n"
    "File a work item with /intake <text> — or /incident <text> / "
    "/request <text> when you already know which it is."
)

# Command → declared work_item_type (None = let Classification decide).
_INTAKE_COMMANDS: dict[str, str | None] = {
    "/intake": None,
    "/incident": "incident",
    "/request": "service_request",
}


def split_reply(text: str) -> list[str]:
    """Split a reply into Telegram-sized chunks; never return an empty list."""
    if not text:
        return ["(empty response)"]
    return [text[i : i + _MAX_MESSAGE_CHARS] for i in range(0, len(text), _MAX_MESSAGE_CHARS)]


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    """Static configuration for one bot instance."""

    bot_token: str
    allowed_chat_ids: frozenset[int]
    api_url: str = "http://127.0.0.1:8001"
    api_token: str | None = None
    poll_timeout_s: int = 50


@dataclass
class _ChatState:
    history: list[dict[str, str]] = field(default_factory=list)


class TelegramChannel:
    """Long-poll loop mapping Telegram messages onto the OpsPilot chat API."""

    def __init__(
        self,
        config: TelegramConfig,
        chat_client: OpsPilotChatClient | None = None,
        http: httpx.Client | None = None,
        run_client: OpsPilotRunClient | None = None,
    ) -> None:
        self._cfg = config
        self._chat = chat_client or OpsPilotChatClient(
            api_url=config.api_url, api_token=config.api_token
        )
        self._run = run_client or OpsPilotRunClient(
            api_url=config.api_url, api_token=config.api_token
        )
        self._http = http or httpx.Client(timeout=config.poll_timeout_s + 10)
        self._api_base = f"https://api.telegram.org/bot{config.bot_token}"
        self._states: dict[int, _ChatState] = {}
        self._offset = 0

    # ── update handling (unit-testable, no polling involved) ──────────────

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or not text:
            return
        if chat_id not in self._cfg.allowed_chat_ids:
            logger.warning("dropping message from non-allowlisted chat %s", chat_id)
            return

        if text == "/start":
            self._send(chat_id, _GREETING)
            return
        if text == "/reset":
            self._states.pop(chat_id, None)
            self._send(chat_id, "Conversation cleared.")
            return
        command, _, rest = text.partition(" ")
        if command in _INTAKE_COMMANDS:
            self._handle_intake(chat_id, message, command, rest.strip())
            return

        state = self._states.setdefault(chat_id, _ChatState())
        messages = [*state.history, {"role": "user", "content": text}]
        try:
            answer = self._chat.ask(messages)
        except Exception as exc:  # noqa: BLE001 — report, keep polling
            logger.error("chat request failed for chat %s: %s", chat_id, exc)
            self._send(chat_id, f"OpsPilot error: {exc}")
            return

        state.history = [
            *messages,
            {"role": "assistant", "content": answer},
        ][-_MAX_HISTORY_MESSAGES:]
        self._send(chat_id, answer)

    def _handle_intake(
        self, chat_id: int, message: dict[str, Any], command: str, text: str
    ) -> None:
        """File the message as a Work item and reply with the suggestion (ADR-0014)."""
        if not text:
            self._send(chat_id, f"Usage: {command} <description of the issue or request>")
            return
        work_item: dict[str, Any] = {
            "ticket_id": f"TG-{chat_id}-{message.get('message_id', 0)}",
            "subject": text.splitlines()[0][:80],
            "body": text,
        }
        declared = _INTAKE_COMMANDS[command]
        if declared:
            work_item["work_item_type"] = declared
        self._send(chat_id, "Filing as a work item — one moment…")
        try:
            res = self._run.run(work_item)
        except Exception as exc:  # noqa: BLE001 — report, keep polling
            logger.error("intake run failed for chat %s: %s", chat_id, exc)
            self._send(chat_id, f"OpsPilot error: {exc}")
            return
        if res.get("needs_confirmation"):
            self._send(
                chat_id,
                "I could not confidently classify this. Resend as "
                "/incident <text> or /request <text>.",
            )
            return
        if res.get("error") or not res.get("schema_valid"):
            self._send(
                chat_id,
                f"Run failed: {res.get('error') or 'artifact failed schema validation'}",
            )
            return
        self._send(
            chat_id, render_comment(res["result"], session_id=str(res.get("session_id", "")))
        )

    # ── Telegram Bot API plumbing ──────────────────────────────────────────

    def _send(self, chat_id: int, text: str) -> None:
        for chunk in split_reply(text):
            res = self._http.post(
                f"{self._api_base}/sendMessage",
                json={"chat_id": chat_id, "text": chunk},
            )
            if res.status_code != 200:
                logger.error("sendMessage failed (%s): %s", res.status_code, res.text[:200])

    def _poll_once(self) -> None:
        res = self._http.get(
            f"{self._api_base}/getUpdates",
            params={"timeout": self._cfg.poll_timeout_s, "offset": self._offset},
        )
        res.raise_for_status()
        for update in res.json().get("result", []):
            self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
            self.handle_update(update)

    def run_forever(self) -> None:
        """Poll until interrupted; transient errors back off and retry."""
        logger.info(
            "telegram channel up — %d allowlisted chat(s), api=%s",
            len(self._cfg.allowed_chat_ids),
            self._cfg.api_url,
        )
        while True:
            try:
                self._poll_once()
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001 — keep the channel alive
                logger.error("poll failed, retrying in 5s: %s", exc)
                time.sleep(5)
