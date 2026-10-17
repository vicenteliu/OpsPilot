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


class Notifier(Protocol):
    """Best-effort push of a delivered suggestion to a notify-mode Channel.

    Called after the comment reaches the Source; a raise is logged and
    never fails the pass — the durable record is the comment itself.
    """

    def notify(self, key: str, body: str) -> None: ...


class SourceTransport(Protocol):
    """How one Source is fetched from and written back to.

    ``marker`` is the idempotency token for one run (the session id): a
    transport that can inspect existing comments must skip the post when
    the marker is already present, so a retry after a lost response never
    duplicates a comment.
    """

    def fetch_new(self) -> list[SourceItem]: ...

    def post_comment(self, key: str, body: str, marker: str) -> None: ...

    def fetch_reply(self, key: str) -> str | None:
        """What was said on ``key`` since OpsPilot last commented, or None (#229)."""
        ...

    def fetch_open_items(self, key: str) -> list[dict[str, Any]]:
        """Open Work items filed in the last hour, other than ``key`` (#230).

        Each is ``{"key", "subject", "body"}``: decision 3 asks whether ``key``
        is the same problem as one of them.
        """
        ...


class OpsPilotRunClient:
    """Calls ``POST /api/run`` and returns the parsed response body.

    ``playbook_id`` pins every run to one server-side playbook (the API
    then skips Classification); ``model_id`` overrides the model per run
    and must be the effective playbook's primary or one of its
    ``extra_models``. Both default to the server's own defaults.
    """

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8001",
        api_token: str | None = None,
        http: httpx.Client | None = None,
        timeout_s: float = 300.0,
        playbook_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_token = api_token
        self._http = http or httpx.Client(timeout=timeout_s)
        self._playbook_id = playbook_id
        self._model_id = model_id

    def run(
        self,
        work_item: dict[str, Any],
        *,
        asked: bool = False,
        open_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run one Work item; ``asked`` when it carries the reply to OpsPilot's one ask.

        ``open_items`` are the source's open Work items from the last hour (#230).
        """
        headers = {"Content-Type": "application/json"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        payload: dict[str, Any] = {"input": work_item}
        if asked:
            payload["asked"] = True
        if open_items:
            payload["open_items"] = open_items
        if self._playbook_id:
            payload["playbook_id"] = self._playbook_id
        if self._model_id:
            payload["model_id"] = self._model_id
        res = self._http.post(f"{self._api_url}/api/run", json=payload, headers=headers)
        res.raise_for_status()
        return dict(res.json())


# Every comment OpsPilot writes opens with this, so a reply is told from its own.
OPSPILOT_HEADING = "## OpsPilot"

_FOOTER = (
    "_Advisory only — suggested by OpsPilot (session `{session_id}`); "
    "the system of record owns the final values._"
)


def _already_open_line(already_open: dict[str, Any] | None) -> list[str]:
    """The open Work item decision 3 named, for a person to link; OpsPilot links nothing (#230)."""
    if not already_open:
        return []
    p = float(already_open.get("probability") or 0.0)
    return [
        f"**Already open?** This looks like the same problem as {already_open['key']} "
        f"(p={p:.2f}). A person should link them; OpsPilot links nothing.",
        "",
    ]


_ENTITLED = {
    True: "yes",
    False: "no, a person checks",
    None: "not known (no submitter role), a person checks",
}


def _catalog_lines(catalog: dict[str, Any] | None) -> list[str]:
    """The catalog item and what was looked up for it, never decided by a model (#231)."""
    if not catalog:
        return []
    if not catalog.get("item"):
        return ["**Catalog item:** not matched, so a person checks the item and its approval.", ""]
    approval = catalog.get("approval", "none")
    parts = [
        f"**Catalog item:** {catalog.get('name', catalog['item'])}",
        f"**Approval:** {'none needed' if approval == 'none' else approval}",
        f"**Entitled:** {_ENTITLED[catalog.get('entitled')]}",
    ]
    if catalog.get("stock_category"):
        parts.append(f"**In stock:** {catalog.get('in_stock', 0)} {catalog['stock_category']}")
    lines = [" · ".join(parts)]
    if catalog.get("fields"):
        lines.append(f"**Needs:** {', '.join(catalog['fields'])}")
    return [*lines, "_Looked up in the service catalog, not decided by a model._", ""]


def render_change_comment(really: dict[str, Any]) -> str:
    """Render a request r2 finds is a change: a person's, OpsPilot having no change path (#293)."""
    p = float(really.get("probability") or 0.0)
    return "\n".join(
        [
            f"{OPSPILOT_HEADING}: a person is needed, this looks like a change",
            "",
            f"Filed as a service request, this reads as a change to a shared service or its "
            f"configuration (p={p:.2f}). OpsPilot has no change path, so it made no suggestion.",
            "",
            "_A person should handle it; the system of record owns the final values._",
        ]
    )


def render_automated_comment(catalog: dict[str, Any]) -> str:
    """Render a catalog item the organisation's own automation fulfils (#231)."""
    return "\n".join(
        [
            f"{OPSPILOT_HEADING}: fulfilled by automation",
            "",
            f"**Catalog item:** {catalog.get('name', catalog.get('item'))}. The catalog says it is "
            "fulfilled automatically, so there is no Task for a person. OpsPilot ran nothing.",
            "",
            "_Looked up in the service catalog; the system of record owns the final values._",
        ]
    )


def render_comment(
    result: dict[str, Any],
    *,
    session_id: str,
    already_open: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
    really: dict[str, Any] | None = None,
) -> str:
    """Render a run artifact as one structured, source-agnostic comment."""
    lines = [f"{OPSPILOT_HEADING} suggestion", ""]
    if really and really.get("answer") == "incident":
        p = float(really.get("probability") or 0.0)
        lines += [f"**Filed as a request, handled as an Incident** (p={p:.2f}).", ""]
    lines += _already_open_line(already_open)
    lines += _catalog_lines(catalog)
    if result.get("summary"):
        lines += [str(result["summary"]), ""]
    if result.get("requested_item"):
        lines.append(f"**Requested item:** {result['requested_item']}")
    if "approval_needed" in result:
        lines.append(f"**Approval needed:** {'yes' if result['approval_needed'] else 'no'}")
    if result.get("severity_suggested"):
        lines.append(f"**Suggested severity:** {result['severity_suggested']}")
    if result.get("escalation_hint"):
        # The team decision 6 picked, or that a person picks it (#228).
        lines.append(f"**Escalation:** {result['escalation_hint']}")
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


def render_needs_person_comment(classification: dict[str, Any]) -> str:
    """Render a run withheld below the Classification threshold (ADR-0040).

    Names the undecided decision and its probability, so the item reaches a
    person where the work lives instead of being marked processed and dropped.
    """
    lean = classification.get("work_item_type", "?")
    p = float(classification.get("confidence", 0.0))
    return "\n".join(
        [
            "## OpsPilot: a person is needed",
            "",
            f"OpsPilot could not decide incident or request (leaning `{lean}`, p={p:.2f}); "
            "a person should pick.",
            "",
            "_No suggestion was made; the system of record owns the final values._",
        ]
    )


def render_ask_comment(ask: dict[str, Any], already_open: dict[str, Any] | None = None) -> str:
    """Render the one ask, when decision 4 says the Work item is too thin to act on (#229)."""
    return "\n".join(
        [
            f"{OPSPILOT_HEADING}: more information needed",
            "",
            *_already_open_line(already_open),
            str(ask.get("text", "")),
            "",
            "_Reply in a comment here; OpsPilot reads the reply and suggests again._",
        ]
    )


def with_reply(work_item: dict[str, Any], reply: str) -> dict[str, Any]:
    """The Work item as first filed, with what was said after the ask (#229).

    On Telegram that is the reporter's next message; on JSM, every comment
    since OpsPilot's, whoever wrote it, so it is not called the reporter's.

    It keeps the type it was asked about as, an Incident (decision 4) unless it
    says a request (r3, #294), so decision 2 is not asked again.
    """
    body = str(work_item.get("body") or "")
    return {
        **work_item,
        "body": f"{body}\n\nAdded after OpsPilot asked for more information:\n{reply}".strip(),
        "work_item_type": work_item.get("work_item_type") or "incident",
    }


def render_security_comment(security: dict[str, Any]) -> str:
    """Render a run stopped at decision 1, a possible security issue (ADR-0040, #225).

    Says why the item stopped, not what to pick: nothing after decision 1 was
    asked, and a security issue is a person's to handle, whatever its type.
    """
    if security.get("fallback"):
        why = (
            "the security check could not complete, so OpsPilot could not rule a security "
            f"event out ({security['fallback']})."
        )
    else:
        # The P(yes) the stage cut on, as the stage computed it.
        p_yes = float(security.get("p_yes") or 0.0)
        why = f"this Work item may report a security event (p(yes)={p_yes:.2f})."
    return "\n".join(
        [
            "## OpsPilot: a person is needed, possible security issue",
            "",
            f"OpsPilot stopped before suggesting anything: {why} It was not classified, no "
            "knowledge-base fix was offered, and no Playbook ran.",
            "",
            "_A person should handle it; the system of record owns the final values._",
        ]
    )


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
        # key → the Work item as filed, while its reporter is asked for more (#229)
        self._awaiting: dict[str, dict[str, Any]] = {}
        if path is not None and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self._processed = set(data.get("processed", []))
            self._pending = dict(data.get("pending_comments", {}))
            self._awaiting = dict(data.get("awaiting_reply", {}))

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
        if key not in self._processed and key not in self._pending and key not in self._awaiting:
            return False
        self._processed.discard(key)
        self._pending.pop(key, None)
        self._awaiting.pop(key, None)
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

    def awaiting_reply(self) -> dict[str, dict[str, Any]]:
        """Keys whose reporter was asked for more, with each Work item as filed (#229)."""
        return dict(self._awaiting)

    def await_reply(self, key: str, work_item: dict[str, Any]) -> None:
        self._awaiting[key] = work_item
        self._save()

    def resolve_reply(self, key: str) -> None:
        self._awaiting.pop(key, None)
        self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "processed": sorted(self._processed),
                    "pending_comments": self._pending,
                    "awaiting_reply": self._awaiting,
                },
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
        notifier: Notifier | None = None,
    ) -> None:
        self._transport = transport
        self._client = client
        self._state = state or IntakeState()
        self._notifier = notifier

    def run_once(self) -> IntakeReport:
        report = IntakeReport()
        self._flush_pending(report)
        self._take_replies(report)
        for item in self._transport.fetch_new():
            if self._state.has(item.key):
                report.skipped.append((item.key, "duplicate"))
                continue
            try:
                res = self._client.run(item.work_item, open_items=self._open_items(item.key))
            except Exception as exc:  # noqa: BLE001 — not marked: retries next pass
                logger.error("run failed for %s (will retry next pass): %s", item.key, exc)
                report.skipped.append((item.key, f"run failed: {exc}"))
                continue
            self._state.mark(item.key)
            if res.get("ask"):
                # The reporter is asked once; their reply runs it again, as the
                # type it was asked about as (#229, #294).
                asked_as = res["ask"].get("work_item_type") or "incident"
                self._state.await_reply(item.key, {**item.work_item, "work_item_type": asked_as})
            self._respond(item.key, res, report)
        return report

    def _take_replies(self, report: IntakeReport) -> None:
        """Run again each asked-about key whose reporter has replied, once (#229)."""
        for key, work_item in self._state.awaiting_reply().items():
            try:
                reply = self._transport.fetch_reply(key)
                if not reply:
                    continue
                res = self._client.run(
                    with_reply(work_item, reply), asked=True, open_items=self._open_items(key)
                )
            except Exception as exc:  # noqa: BLE001 — still awaiting: retries next pass
                logger.error("reply run failed for %s (will retry next pass): %s", key, exc)
                report.skipped.append((key, f"reply run failed: {exc}"))
                continue
            self._state.resolve_reply(key)
            self._respond(key, res, report)

    def _open_items(self, key: str) -> list[dict[str, Any]]:
        """The source's open Work items for decision 3; none when they cannot be read (#230)."""
        try:
            return self._transport.fetch_open_items(key)
        except Exception as exc:  # noqa: BLE001 — decision 3 is advisory; run without it
            logger.warning("open Work items unread for %s; no match is named: %s", key, exc)
            return []

    def _respond(self, key: str, res: dict[str, Any], report: IntakeReport) -> None:
        """Turn one run's response into the comment it calls for."""
        security = res.get("security") or {}
        if security.get("stops"):
            self._deliver(key, render_security_comment(security), "", report)
            return
        if (res.get("really") or {}).get("answer") == "change":
            self._deliver(key, render_change_comment(res["really"]), "", report)
            return
        if (res.get("catalog") or {}).get("automated"):
            self._deliver(key, render_automated_comment(res["catalog"]), "", report)
            return
        if res.get("ask"):
            body = render_ask_comment(res["ask"], res.get("already_open"))
            self._deliver(key, body, "", report)
            return
        if res.get("needs_confirmation"):
            # No run happened, so there is no session id to mark the comment
            # with: a retry after a lost response can post it twice.
            body = render_needs_person_comment(res.get("classification") or {})
            self._deliver(key, body, "", report)
            return
        reason = _unusable(res)
        if reason:
            logger.warning("no comment for %s: %s", key, reason)
            report.skipped.append((key, reason))
            return
        session_id = str(res.get("session_id", ""))
        body = render_comment(
            res["result"],
            session_id=session_id,
            already_open=res.get("already_open"),
            catalog=res.get("catalog"),
            really=res.get("really"),
        )
        self._deliver(key, body, session_id, report)

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
        if self._notifier is not None:
            try:
                self._notifier.notify(key, body)
            except Exception as exc:  # noqa: BLE001 — courtesy copy only, never fail the pass
                logger.warning("notify failed for %s: %s", key, exc)

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
