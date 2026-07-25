"""Source-agnostic Work-item intake: contract, API client, loop (ADR-0013).

A Source is an external system of record OpsPilot pulls Work items from;
Intake is the poll → normalize → dedupe → run → write-back loop connecting
it to the pipeline. Adapters are separate processes reaching the pipeline
over HTTP (ADR-0012 pattern) rather than importing the orchestrator
in-process.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
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
    """How one Source is fetched from and written back to.

    ``marker`` is the idempotency token for one run (the session id): a
    transport that can inspect existing comments must skip the post when
    the marker is already present, so a retry after a lost response never
    duplicates a comment.
    """

    def fetch_new(self) -> list[SourceItem]: ...

    def post_comment(self, key: str, body: str, marker: str) -> None: ...


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


class IntakeState:
    """Processed-key state that survives adapter restarts (#58).

    Operational state only — which keys already ran; the Source remains
    the system of record for the Work items themselves (ADR-0006). With
    no path, state is in-memory (tests, throwaway passes). No poll cursor
    on purpose: every pass re-fetches the full intake scope, so an issue
    created while the adapter was down is picked up on the next pass.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._processed: set[str] = set()
        self._pending: dict[str, dict[str, str]] = {}  # key → {"body", "marker"}
        if path is not None and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self._processed = set(data.get("processed", []))
            self._pending = dict(data.get("pending_comments", {}))

    def has(self, key: str) -> bool:
        return key in self._processed

    def mark(self, key: str) -> None:
        self._processed.add(key)
        self._save()

    def forget(self, key: str) -> bool:
        """Drop a key so it runs again (--rerun). True if it was present.

        Any queued comment for the key is dropped too — the fresh run
        produces a fresh suggestion.
        """
        if key not in self._processed and key not in self._pending:
            return False
        self._processed.discard(key)
        self._pending.pop(key, None)
        self._save()
        return True

    def pending_comments(self) -> dict[str, dict[str, str]]:
        """Comments rendered but not yet delivered (post failed earlier)."""
        return dict(self._pending)

    def queue_comment(self, key: str, body: str, marker: str) -> None:
        self._pending[key] = {"body": body, "marker": marker}
        self._save()

    def resolve_comment(self, key: str) -> None:
        self._pending.pop(key, None)
        self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"processed": sorted(self._processed), "pending_comments": self._pending},
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(self._path)


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

    One run per key: a key is marked processed once a run *returns*
    (success or a deterministic non-comment outcome). A run that raises —
    server down, provider outage — is NOT marked, so it retries on the
    next pass. Manual reruns go through ``IntakeState.forget``.
    """

    def __init__(
        self,
        transport: SourceTransport,
        client: OpsPilotRunClient,
        state: IntakeState | None = None,
    ) -> None:
        self._transport = transport
        self._client = client
        self._state = state or IntakeState()

    def run_once(self) -> IntakeReport:
        report = IntakeReport()
        self._flush_pending(report)
        for item in self._transport.fetch_new():
            if self._state.has(item.key):
                report.skipped.append((item.key, "duplicate"))
                continue
            try:
                res = self._client.run(item.work_item)
            except Exception as exc:  # noqa: BLE001 — not marked: retries next pass
                logger.error("run failed for %s (will retry next pass): %s", item.key, exc)
                report.skipped.append((item.key, f"run failed: {exc}"))
                continue
            self._state.mark(item.key)
            reason = _unusable(res)
            if reason:
                logger.warning("no comment for %s: %s", item.key, reason)
                report.skipped.append((item.key, reason))
                continue
            session_id = str(res.get("session_id", ""))
            body = render_comment(res["result"], session_id=session_id)
            self._deliver(item.key, body, session_id, report)
        return report

    def _deliver(self, key: str, body: str, marker: str, report: IntakeReport) -> None:
        """Post one comment; a failed post is queued and retried next pass
        without re-running the LLM."""
        try:
            self._transport.post_comment(key, body, marker)
        except Exception as exc:  # noqa: BLE001 — queue, keep the pass alive
            logger.error("comment post failed for %s (queued for retry): %s", key, exc)
            self._state.queue_comment(key, body, marker)
            report.skipped.append((key, f"comment post failed (queued): {exc}"))
            return
        self._state.resolve_comment(key)
        report.commented.append(key)

    def _flush_pending(self, report: IntakeReport) -> None:
        for key, entry in self._state.pending_comments().items():
            self._deliver(key, entry["body"], entry["marker"], report)

    def run_forever(self, interval_s: float) -> None:
        """Poll until interrupted; a failed pass (e.g. Source outage) backs
        off one interval and retries instead of crash-looping."""
        while True:
            try:
                report = self.run_once()
                logger.info(
                    "intake pass done — %d commented, %d skipped",
                    len(report.commented),
                    len(report.skipped),
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001 — keep the adapter alive
                logger.error("intake pass failed, retrying in %ss: %s", interval_s, exc)
            time.sleep(interval_s)
