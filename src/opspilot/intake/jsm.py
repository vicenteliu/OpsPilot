"""Jira Service Management Source adapter — replay transport (ADR-0013).

The tracer-bullet transport replays recorded JSM API responses from a
fixtures directory and writes suggestion comments to an output directory
instead of posting them back. Live REST polling lands with #57.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import SourceItem

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

    def post_comment(self, key: str, body: str) -> None:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        (self._out_dir / f"{key}.md").write_text(body, encoding="utf-8")
