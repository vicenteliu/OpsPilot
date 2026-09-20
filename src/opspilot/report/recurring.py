"""Recurring-class report over archived incident summaries (#220, ADR-0039).

Input is what every run already leaves behind: an archived Session whose
artifact is an ``incident_summary_v1``. No new data source, no model call —
the cause class was named by the run that produced the artifact
(``cause_class``), and artifacts from before that field existed roll up as
``unclassified`` rather than being guessed at now.

Output: per cause class in the period — count, share of incidents, the
severities inside it, the KB pages it cited most, and the one fix that stops
the class recurring. The fix per class is a fixed sentence, not a generated
one: what a class *means* was decided when the class was defined, and the
report's job is to say which class the period's tickets fell into.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from ..session.manager import SessionManager
from ..timeutil import now_rfc3339, parse_rfc3339

INCIDENT_SCHEMA: Final = "incident_summary_v1"

CAUSE_CLASSES: Final[tuple[str, ...]] = (
    "user_error",
    "server_side",
    "process_or_kb_gap",
    "unknown",
)
UNCLASSIFIED: Final = "unclassified"  # the artifact predates cause_class

RECOMMENDED_FIX: Final[dict[str, str]] = {
    "user_error": (
        "The KB already answers these; point the intake at the cited page. "
        "If one page keeps being cited, the page or the training is what to fix."
    ),
    "server_side": (
        "A change on the server side. File it against the cited component; "
        "this class's tickets are the evidence for the change request."
    ),
    "process_or_kb_gap": (
        "Update the cited KB page or the intake form so the next ticket of this "
        "class does not need a person."
    ),
    "unknown": (
        "The run could not name a cause. Read a sample of these by hand before deciding anything."
    ),
    UNCLASSIFIED: (
        "Runs from before cause_class existed. Re-run a sample to classify them, "
        "or leave them out of the decision."
    ),
}

_TOP_PAGES: Final = 3


@dataclass(frozen=True)
class ClassRow:
    """One cause class in the period."""

    cause_class: str
    count: int
    share: float  # of incidents in the period, 0..1
    severities: dict[str, int]  # severity_suggested → count
    top_pages: list[tuple[str, int]]  # (source_path or document_id, citations)
    work_item_refs: list[str]
    recommended_fix: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause_class": self.cause_class,
            "count": self.count,
            "share": round(self.share, 4),
            "severities": dict(self.severities),
            "top_pages": [{"page": p, "citations": n} for p, n in self.top_pages],
            "work_item_refs": list(self.work_item_refs),
            "recommended_fix": self.recommended_fix,
        }


@dataclass(frozen=True)
class RecurringReport:
    since: str | None
    until: str | None
    generated_at: str
    sessions_seen: int  # archived sessions in the period
    incidents: int  # of those, with an incident_summary_v1 artifact
    rows: list[ClassRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": "recurring_classes_v1",
            "since": self.since,
            "until": self.until,
            "generated_at": self.generated_at,
            "sessions_seen": self.sessions_seen,
            "incidents": self.incidents,
            "classes": [r.to_dict() for r in self.rows],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        period = f"{self.since or 'start'} → {self.until or 'now'}"
        out = [
            "# Recurring classes",
            "",
            f"Period {period} · generated {self.generated_at}",
            f"Archived sessions {self.sessions_seen} · incidents with a summary {self.incidents}",
            "",
        ]
        if not self.rows:
            out.append("_No archived incident summaries in this period._")
            return "\n".join(out) + "\n"
        out += [
            "| class | count | share | severities | pages cited most |",
            "|---|---|---|---|---|",
        ]
        for r in self.rows:
            sev = " ".join(f"{k}×{v}" for k, v in sorted(r.severities.items())) or "—"
            pages = "; ".join(f"`{p}` ×{n}" for p, n in r.top_pages) or "—"
            out.append(f"| `{r.cause_class}` | {r.count} | {r.share:.0%} | {sev} | {pages} |")
        out.append("")
        for r in self.rows:
            out += [
                f"## `{r.cause_class}` — {r.count} ({r.share:.0%})",
                "",
                f"**Fix:** {r.recommended_fix}",
                "",
                "Work items: " + ", ".join(r.work_item_refs),
                "",
            ]
        out.append("_The report recommends; a person decides which fix to make (ADR-0006)._")
        return "\n".join(out) + "\n"


def build_recurring_report(
    sm: SessionManager,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> RecurringReport:
    """Roll up every archived incident summary created in ``[since, until]``.

    A session counts when it is ``archived`` (the run finished) and its
    ``created_at`` falls in the period. The **newest** ``incident_summary_v1``
    artifact in the session is the one read; sessions with none are seen but
    not counted as incidents.
    """
    sessions_seen = 0
    per_class: dict[str, list[dict[str, Any]]] = {}
    for sid in sm.list():
        sess = sm.load(sid)
        if sess.status != "archived":
            continue
        created = parse_rfc3339(sess.created_at)
        if since is not None and created < since:
            continue
        if until is not None and created > until:
            continue
        sessions_seen += 1
        summary = _last_incident_summary(sm, sid)
        if summary is None:
            continue
        cls = summary.get("cause_class")
        if cls not in CAUSE_CLASSES:
            cls = UNCLASSIFIED
        per_class.setdefault(cls, []).append(summary)

    incidents = sum(len(v) for v in per_class.values())
    rows: list[ClassRow] = []
    for cls, summaries in per_class.items():
        sev = Counter(str(s.get("severity_suggested", "?")) for s in summaries)
        pages = Counter(_page_key(c) for s in summaries for c in s.get("citations", []))
        rows.append(
            ClassRow(
                cause_class=cls,
                count=len(summaries),
                share=len(summaries) / incidents,
                severities=dict(sev),
                top_pages=pages.most_common(_TOP_PAGES),
                work_item_refs=[str(s.get("work_item_ref", "?")) for s in summaries],
                recommended_fix=RECOMMENDED_FIX[cls],
            )
        )
    # Biggest class first; unclassified last regardless of size — it is not a
    # finding, it is the part of the corpus the report cannot speak for.
    rows.sort(key=lambda r: (r.cause_class == UNCLASSIFIED, -r.count, r.cause_class))

    return RecurringReport(
        since=since.isoformat() if since else None,
        until=until.isoformat() if until else None,
        generated_at=now_rfc3339(),
        sessions_seen=sessions_seen,
        incidents=incidents,
        rows=rows,
    )


def _last_incident_summary(sm: SessionManager, session_id: str) -> dict[str, Any] | None:
    store = sm.artifacts(session_id)
    found: tuple[str, dict[str, Any]] | None = None
    for art_id in store.list_ids():
        meta = store.get_meta(art_id)
        if meta.kind != "application/json":
            continue
        try:
            data = json.loads(store.read_text(art_id))
        except (ValueError, UnicodeDecodeError):
            continue
        if not (isinstance(data, dict) and data.get("schema_version") == INCIDENT_SCHEMA):
            continue
        # Ids are content hashes, so list order says nothing; the newest
        # sidecar is the run's final answer.
        if found is None or meta.created_at > found[0]:
            found = (meta.created_at, data)
    return found[1] if found else None


def _page_key(citation: dict[str, Any]) -> str:
    return str(citation.get("source_path") or citation.get("document_id") or "?")
