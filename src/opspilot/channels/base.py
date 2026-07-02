"""Client used by channel adapters to talk to a running OpsPilot API.

Channels are separate processes: they reach the chat pipeline over HTTP
(loopback by default, or a remote deployment with a bearer token per
ADR-0011) rather than importing the orchestrator in-process, so one code
path serves the web UI and every channel.
"""

from __future__ import annotations

import json

import httpx


class OpsPilotChatClient:
    """Calls ``POST /api/chat/stream`` and returns the final answer text."""

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8001",
        api_token: str | None = None,
        http: httpx.Client | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_token = api_token
        self._http = http or httpx.Client(timeout=timeout_s)

    def ask(self, messages: list[dict[str, str]]) -> str:
        """Send the conversation; block until the SSE stream yields a result.

        Raises ``RuntimeError`` with the server's message on an error event.
        """
        headers = {"Content-Type": "application/json"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"

        res = self._http.post(
            f"{self._api_url}/api/chat/stream",
            json={"messages": messages},
            headers=headers,
        )
        res.raise_for_status()

        event = "message"
        for line in res.text.splitlines():
            if line.startswith("event: "):
                event = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                payload = json.loads(line[len("data: ") :])
                if event == "result":
                    return str(payload.get("content", ""))
                if event == "error":
                    raise RuntimeError(payload.get("message", "chat failed"))
        raise RuntimeError("chat stream ended without a result")
