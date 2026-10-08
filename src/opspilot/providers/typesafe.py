"""TypeSafe client, the ``typesafe`` provider kind (ADR-0040).

A thin client over the two endpoints Jev's Judgments need:

* ``POST /v1/systemone``: a state and named questions in, one answer per
  question out, with token usage.
* ``GET /v1/models``: the model names the account may ask for.

The wire shapes follow typesafe-sdk 0.7.2, whose models are generated from
``https://api.typesafe.ai/openapi.json``. The SDK itself is not a dependency:
it pulls in ``httpx2``, and two endpoints do not justify a second HTTP stack.
This client returns the decoded JSON; what an answer means is the Judge's
business (``opspilot.judgment.TypeSafeJudge``).
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from ..errors import ProviderError

DEFAULT_BASE_URL: Final = "https://api.typesafe.ai"
DEFAULT_MODEL: Final = "jev-latest"
DEFAULT_TIMEOUT_S: Final = 10.0


class TypeSafeClient:
    """The TypeSafe API over plain ``httpx``."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        # Allow injection for tests (e.g. httpx.MockTransport-backed Client).
        self._client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_s)
        self.base_url = self._client.base_url
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def system_one(
        self, state: str, questions: dict[str, Any], *, model: str, timeout_s: float
    ) -> dict[str, Any]:
        body = {"state": state, "model": model, "questions": questions}
        return self._request("POST", "/v1/systemone", body, timeout_s)

    def models(self) -> list[str]:
        data = self._request("GET", "/v1/models", None, self.timeout_s)
        try:
            return [str(m["name"]) for m in data["models"]]
        except (KeyError, TypeError) as e:
            raise ProviderError(f"TypeSafe models: malformed response: {data!r}") from e

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None, timeout_s: float
    ) -> dict[str, Any]:
        try:
            r = self._client.request(
                method, path, json=body, headers=self._headers, timeout=timeout_s
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"TypeSafe {path} HTTP {e.response.status_code}: {e.response.text[:200]}",
                error_code=f"http_{e.response.status_code}",
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError(f"timed out after {timeout_s}s", error_code="timeout_read") from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"TypeSafe {path} network error: {e}", error_code="network_error"
            ) from e
        try:
            data = r.json()
        except ValueError as e:
            raise ProviderError(f"TypeSafe {path}: response is not JSON: {r.text[:200]}") from e
        if not isinstance(data, dict):
            raise ProviderError(f"TypeSafe {path}: response is not an object: {data!r}")
        return data
