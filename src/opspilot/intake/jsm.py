"""Jira Service Management Source adapter (ADR-0013).

Two transports share one normalizer and one comment template:
``ReplayTransport`` replays recorded JSM API responses from a fixtures
directory and writes comments to a local sink; ``JsmTransport`` polls a
live JSM site over REST (outbound-only — no webhooks, no inbound
exposure) and posts the suggestion back to the issue as a comment.
Comment-only write-back: no JSM field is ever mutated (ADR-0006).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from .base import SourceItem

logger = logging.getLogger("opspilot.intake.jsm")

_TYPE_HINTS = (("incident", "incident"), ("request", "service_request"))


def _declared_type(issuetype_name: str) -> str | None:
    """Map a JSM issue-type name onto a declared Work item type, if obvious."""
    name = issuetype_name.lower()
    for hint, wtype in _TYPE_HINTS:
        if hint in name:
            return wtype
    return None


def normalize_issue(issue: dict[str, Any]) -> SourceItem:
    """Map one Jira issue (REST v2 shape) onto a pipeline Work item."""
    key = str(issue["key"])
    fields = issue.get("fields") or {}
    work_item: dict[str, Any] = {
        "ticket_id": key,
        "subject": fields.get("summary") or "",
        "body": fields.get("description") or "",
    }
    declared = _declared_type(str((fields.get("issuetype") or {}).get("name", "")))
    if declared:
        work_item["work_item_type"] = declared
    return SourceItem(key=key, work_item=work_item, url=issue.get("self"))


class ReplayTransport:
    """Replays a recorded ``search.json``; comments land in ``out_dir``."""

    def __init__(self, fixtures_dir: Path, out_dir: Path) -> None:
        self._fixtures_dir = fixtures_dir
        self._out_dir = out_dir

    def fetch_new(self) -> list[SourceItem]:
        payload = json.loads((self._fixtures_dir / "search.json").read_text(encoding="utf-8"))
        return [normalize_issue(issue) for issue in payload.get("issues", [])]

    def post_comment(self, key: str, body: str, marker: str) -> None:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        (self._out_dir / f"{key}.md").write_text(body, encoding="utf-8")


class JsmTransport:
    """Polls a live JSM site: JQL-scoped REST search, basic auth (#57).

    Only issues matching the configured JQL are ever fetched — the filter
    is the intake scope and the cost boundary (ADR-0013). Pages through
    the full result set so a backlog larger than one page is not silently
    truncated. Write-back (#59) posts the suggestion as a comment on the
    issue and never touches any field; the run's session id doubles as an
    idempotency marker against existing comments, so a retry after a lost
    response cannot double-post.
    """

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        jql: str,
        http: httpx.Client | None = None,
        page_size: int = 50,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._jql = jql
        self._page_size = page_size
        self._auth = httpx.BasicAuth(email, api_token)
        self._http = http or httpx.Client(timeout=30.0)

    def fetch_new(self) -> list[SourceItem]:
        items: list[SourceItem] = []
        start_at = 0
        while True:
            res = self._http.get(
                f"{self._base_url}/rest/api/2/search",
                params={
                    "jql": self._jql,
                    "fields": "summary,description,issuetype",
                    "startAt": start_at,
                    "maxResults": self._page_size,
                },
                auth=self._auth,
            )
            res.raise_for_status()
            payload = res.json()
            issues = payload.get("issues", [])
            items.extend(normalize_issue(issue) for issue in issues)
            start_at += len(issues)
            if not issues or start_at >= int(payload.get("total", 0)):
                return items

    def post_comment(self, key: str, body: str, marker: str) -> None:
        if marker and self._already_commented(key, marker):
            logger.info("comment for %s already posted (marker found) — skipping", key)
            return
        res = self._http.post(
            f"{self._base_url}/rest/api/2/issue/{key}/comment",
            json={"body": body},
            auth=self._auth,
        )
        res.raise_for_status()

    def _already_commented(self, key: str, marker: str) -> bool:
        """True when an existing comment carries this run's session marker."""
        res = self._http.get(
            f"{self._base_url}/rest/api/2/issue/{key}/comment",
            params={"maxResults": 100},
            auth=self._auth,
        )
        res.raise_for_status()
        return any(marker in (c.get("body") or "") for c in res.json().get("comments", []))
