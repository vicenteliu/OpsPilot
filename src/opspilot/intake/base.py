"""Source-agnostic Work-item intake: contract, API client, loop (ADR-0013).

A Source is an external system of record OpsPilot pulls Work items from;
Intake is the poll → normalize → dedupe → run → write-back loop connecting
it to the pipeline. Adapters are separate processes reaching the pipeline
over HTTP (ADR-0012 pattern) rather than importing the orchestrator
in-process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

logger = logging.getLogger("opspilot.intake")


@dataclass(frozen=True, slots=True)
class SourceItem:
    """One Work item pulled from a Source, normalized for POST /api/run."""

    key: str  # source-unique id, e.g. "IT-101"
    work_item: dict[str, Any]  # raw input JSON for the run pipeline
    url: str | None = None  # deep link back to the Source, if any


class SourceTransport(Protocol):
    """How one Source is fetched from and written back to."""

    def fetch_new(self) -> list[SourceItem]: ...

    def post_comment(self, key: str, body: str) -> None: ...


class OpsPilotRunClient:
    """Calls ``POST /api/run`` and returns the parsed response body."""

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8001",
        api_token: str | None = None,
        http: httpx.Client | None = None,
        timeout_s: float = 300.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_token = api_token
        self._http = http or httpx.Client(timeout=timeout_s)

    def run(self, work_item: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        res = self._http.post(
            f"{self._api_url}/api/run", json={"input": work_item}, headers=headers
        )
        res.raise_for_status()
        return dict(res.json())


_FOOTER = (
    "_Advisory only — suggested by OpsPilot (session `{session_id}`); "
    "the system of record owns the final values._"
)


def render_comment(result: dict[str, Any], *, session_id: str) -> str:
    """Render a run artifact as one structured, source-agnostic comment."""
    lines = ["## OpsPilot suggestion", ""]
    if result.get("summary"):
        lines += [str(result["summary"]), ""]
    if result.get("requested_item"):
        lines.append(f"**Requested item:** {result['requested_item']}")
    if "approval_needed" in result:
        lines.append(f"**Approval needed:** {'yes' if result['approval_needed'] else 'no'}")
    if result.get("severity_suggested"):
        lines.append(f"**Suggested severity:** {result['severity_suggested']}")
    tasks = result.get("tasks") or []
    if tasks:
        lines += ["", "**Suggested tasks:**"]
        for t in tasks:
            cites = f" _[{', '.join(t['citations'])}]_" if t.get("citations") else ""
            lines.append(
                f"- `{t.get('tier', '?')}` {t.get('action', '')} — {t.get('rationale', '')}{cites}"
            )
    citations = result.get("citations") or []
    if citations:
        lines += ["", "**KB citations:**"]
        for c in citations:
            lines.append(f"- `{c.get('id')}` {c.get('source_path')} (chunk `{c.get('chunk_id')}`)")
    lines += ["", _FOOTER.format(session_id=session_id)]
    return "\n".join(lines)


@dataclass
class IntakeReport:
    """What one intake pass did."""

    commented: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (key, reason)


def _unusable(res: dict[str, Any]) -> str | None:
    """Reason this run response must not become a comment, or None."""
    if res.get("error"):
        return f"pipeline error: {res['error']}"
    if res.get("needs_confirmation"):
        return "classification needs human confirmation"
    if not res.get("schema_valid"):
        return "artifact failed schema validation"
    return None


class IntakeLoop:
    """Dedupe + run + write-back over one SourceTransport.

    Dedupe is in-memory for now — one run per key per process; persistent
    state across restarts is a follow-up (#58).
    """

    def __init__(self, transport: SourceTransport, client: OpsPilotRunClient) -> None:
        self._transport = transport
        self._client = client
        self._seen: set[str] = set()

    def run_once(self) -> IntakeReport:
        report = IntakeReport()
        for item in self._transport.fetch_new():
            if item.key in self._seen:
                report.skipped.append((item.key, "duplicate"))
                continue
            self._seen.add(item.key)
            try:
                res = self._client.run(item.work_item)
            except Exception as exc:  # noqa: BLE001 — skip this item, keep the pass alive
                logger.error("run failed for %s: %s", item.key, exc)
                report.skipped.append((item.key, f"run failed: {exc}"))
                continue
            reason = _unusable(res)
            if reason:
                logger.warning("no comment for %s: %s", item.key, reason)
                report.skipped.append((item.key, reason))
                continue
            body = render_comment(res["result"], session_id=res.get("session_id", ""))
            self._transport.post_comment(item.key, body)
            report.commented.append(item.key)
        return report
