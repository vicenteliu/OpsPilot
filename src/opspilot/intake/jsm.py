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
import re
from pathlib import Path
from typing import Any

import httpx

from .base import OPSPILOT_HEADING, SourceItem

logger = logging.getLogger("opspilot.intake.jsm")

_TYPE_HINTS = (("incident", "incident"), ("request", "service_request"))
_ORDER_BY = re.compile(r"\s+ORDER\s+BY\s+.*$", re.IGNORECASE | re.DOTALL)
# Open Work items offered to decision 3 at most: the newest, in the intake scope.
OPEN_ITEMS_MAX = 20


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

    def fetch_open_items(self, key: str) -> list[dict[str, Any]]:
        """None: a replay has no clock to say what was filed in the last hour."""
        return []

    def fetch_reply(self, key: str) -> str | None:
        """A recorded reply, ``replies/<key>.txt`` beside ``search.json``, if there is one."""
        path = self._fixtures_dir / "replies" / f"{key}.txt"
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8").strip() or None


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

    def fetch_open_items(self, key: str) -> list[dict[str, Any]]:
        """The intake scope's open issues created in the last hour, other than ``key`` (#230).

        Code builds the list (ADR-0040): the configured JQL, narrowed to the last
        hour and to issues not done, newest first, at most ``OPEN_ITEMS_MAX``.
        """
        scope = _ORDER_BY.sub("", self._jql).strip()
        jql = (
            f'({scope}) AND created >= "-1h" AND statusCategory != Done AND key != "{key}"'
            " ORDER BY created DESC"
        )
        res = self._http.get(
            f"{self._base_url}/rest/api/2/search",
            params={"jql": jql, "fields": "summary,description", "maxResults": OPEN_ITEMS_MAX},
            auth=self._auth,
        )
        res.raise_for_status()
        return [
            {
                "key": str(issue["key"]),
                "subject": (issue.get("fields") or {}).get("summary") or "",
                "body": (issue.get("fields") or {}).get("description") or "",
            }
            for issue in res.json().get("issues", [])
        ]

    def fetch_reply(self, key: str) -> str | None:
        """The comments posted since OpsPilot's last one on ``key``, or None (#229).

        The newest 100, newest first, put back in order: the ask and its reply
        are the latest, however long the issue's history. OpsPilot's own
        comments all open with its heading, so whatever follows the last of
        them, and is not one of them, is what was said on the issue since.
        """
        res = self._http.get(
            f"{self._base_url}/rest/api/2/issue/{key}/comment",
            params={"maxResults": 100, "orderBy": "-created"},
            auth=self._auth,
        )
        res.raise_for_status()
        bodies = [str(c.get("body") or "") for c in reversed(res.json().get("comments", []))]
        ours = [i for i, b in enumerate(bodies) if b.startswith(OPSPILOT_HEADING)]
        since = bodies[ours[-1] + 1 :] if ours else bodies
        said = [b.strip() for b in since if b.strip() and not b.startswith(OPSPILOT_HEADING)]
        return "\n\n".join(said) or None

    def _already_commented(self, key: str, marker: str) -> bool:
        """True when an existing comment carries this run's session marker."""
        res = self._http.get(
            f"{self._base_url}/rest/api/2/issue/{key}/comment",
            params={"maxResults": 100},
            auth=self._auth,
        )
        res.raise_for_status()
        return any(marker in (c.get("body") or "") for c in res.json().get("comments", []))
