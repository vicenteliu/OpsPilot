"""Wiki lint engine — pure-static checks (PR-23).

Checks run without LLM calls:
  orphan           — page has no inbound [[slug]] references from other pages
  broken_link      — body contains [[slug]] that resolves to no existing page
  redaction_warning — body contains a [REDACTED: placeholder (PII leak risk)
  schema_invalid   — page fails to parse, has duplicate slug, or is missing
                     required body sections (summary kind: TL;DR / Key claims /
                     Sources)

Output conforms to wiki/schemas/lint-issue.schema.json.
The extra ``page_slug`` field on LintIssue is for TUI display only and is
omitted from ``to_dict()``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..timeutil import now_rfc3339
from .page import read_page

# ── Regex helpers ─────────────────────────────────────────────────────────────

_LINK_RE = re.compile(r"\[\[([^\]|#\n]+?)\]\]")  # [[slug]] or [[slug|text]]
_REDACTED_RE = re.compile(r"\[REDACTED:", re.IGNORECASE)

# Sections required in summary-kind pages
_SUMMARY_REQUIRED_SECTIONS = ("## TL;DR", "## Key claims", "## Sources")


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LintIssue:
    """One lint finding.  Conforms to lint-issue.schema.json."""

    id: str                          # lnt_<sha8>
    issue_type: str                  # enum per schema
    severity: str                    # low / medium / high / critical
    detected_at: str                 # RFC3339
    scope: dict[str, Any]            # {pages: [page_id]}
    summary: str                     # human-readable ≤500 chars
    suggested_action: dict[str, Any] # {kind, rationale}
    page_slug: str = ""              # for TUI display (not in schema output)
    lint_run_id: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    lifecycle_state: str = "open"

    def to_dict(self) -> dict[str, Any]:
        """Serialise to schema-conformant dict (excludes page_slug)."""
        return {
            "id": self.id,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "detected_at": self.detected_at,
            "lint_run_id": self.lint_run_id,
            "scope": self.scope,
            "summary": self.summary,
            "evidence": self.evidence,
            "suggested_action": self.suggested_action,
            "lifecycle_state": self.lifecycle_state,
        }


# ── Internal helpers ──────────────────────────────────────────────────────────


def _lnt_id(*parts: str) -> str:
    """Derive a stable ``lnt_<sha8>`` id from the given parts."""
    digest = hashlib.sha256(":".join(parts).encode()).hexdigest()[:8]
    return f"lnt_{digest}"


def _link_slugs(body: str) -> list[str]:
    """Extract all [[slug]] (or [[slug|text]]) targets from *body*."""
    return [m.strip() for m in _LINK_RE.findall(body)]


# ── Public API ────────────────────────────────────────────────────────────────


def lint_wiki(wiki_root: Path) -> list[LintIssue]:
    """Run all static lint checks against ``wiki_root/pages/**/*.md``.

    Returns a (possibly empty) list of :class:`LintIssue`.  No LLM or
    network calls are made; every check is purely structural.
    """
    pages_dir = wiki_root / "pages"
    if not pages_dir.is_dir():
        return []

    now = now_rfc3339()
    issues: list[LintIssue] = []

    # ── Pass 1: load pages ────────────────────────────────────────────────────
    # slug → (WikiPage, Path); second occurrence detected as slug collision.
    from .page import WikiPage  # local import to avoid top-level cycle

    pages: dict[str, WikiPage] = {}
    slug_files: dict[str, list[Path]] = {}

    for md_file in sorted(pages_dir.rglob("*.md")):
        try:
            page = read_page(md_file)
        except Exception as exc:  # noqa: BLE001
            issues.append(
                LintIssue(
                    id=_lnt_id("schema_invalid", str(md_file)),
                    issue_type="schema_invalid",
                    severity="high",
                    detected_at=now,
                    scope={"pages": []},
                    summary=f"Failed to parse {md_file.name}: {exc}"[:500],
                    suggested_action={"kind": "redact", "rationale": "Fix malformed frontmatter or body."},
                    page_slug=md_file.stem,
                )
            )
            continue

        slug_files.setdefault(page.slug, []).append(md_file)
        pages[page.slug] = page

    # ── Check: slug collision (schema_invalid) ────────────────────────────────
    for slug, paths in slug_files.items():
        if len(paths) > 1:
            page_id = pages[slug].page_id
            issues.append(
                LintIssue(
                    id=_lnt_id("schema_invalid", "slug_collision", slug),
                    issue_type="schema_invalid",
                    severity="high",
                    detected_at=now,
                    scope={"pages": [page_id]},
                    summary=(
                        f"Slug '{slug}' appears in {len(paths)} files: "
                        + ", ".join(p.name for p in paths)
                    )[:500],
                    suggested_action={
                        "kind": "archive",
                        "rationale": "Rename or archive duplicate page files to restore slug uniqueness.",
                    },
                    page_slug=slug,
                )
            )

    # ── Build link index from [[slug]] patterns ───────────────────────────────
    # outbound[slug] = list of slugs referenced by body
    outbound: dict[str, list[str]] = {slug: _link_slugs(page.body) for slug, page in pages.items()}

    # inbound[slug] = list of slugs that reference it
    inbound: dict[str, list[str]] = {slug: [] for slug in pages}
    for from_slug, refs in outbound.items():
        for ref in refs:
            if ref in inbound:
                inbound[ref].append(from_slug)

    known_slugs = set(pages)

    # ── Per-page checks ───────────────────────────────────────────────────────
    for slug, page in pages.items():
        page_id = page.page_id

        # Check: orphan ───────────────────────────────────────────────────────
        if not inbound[slug] and page.lifecycle_state not in ("archived",):
            issues.append(
                LintIssue(
                    id=_lnt_id("orphan", page_id),
                    issue_type="orphan",
                    severity="medium",
                    detected_at=now,
                    scope={"pages": [page_id]},
                    summary=f"Page '{slug}' has no inbound [[links]] from other pages.",
                    suggested_action={
                        "kind": "add_cross_ref",
                        "rationale": f"Add [[{slug}]] to a related page.",
                    },
                    page_slug=slug,
                )
            )

        # Check: broken_link ──────────────────────────────────────────────────
        seen_broken: set[str] = set()
        for ref_slug in outbound[slug]:
            if ref_slug not in known_slugs and ref_slug not in seen_broken:
                seen_broken.add(ref_slug)
                issues.append(
                    LintIssue(
                        id=_lnt_id("broken_link", page_id, ref_slug),
                        issue_type="broken_link",
                        severity="medium",
                        detected_at=now,
                        scope={"pages": [page_id]},
                        summary=f"Page '{slug}' links to [[{ref_slug}]] which does not exist.",
                        suggested_action={
                            "kind": "create_page",
                            "rationale": f"Create a page with slug '{ref_slug}', or correct the link.",
                        },
                        page_slug=slug,
                    )
                )

        # Check: redaction_warning ────────────────────────────────────────────
        if _REDACTED_RE.search(page.body):
            issues.append(
                LintIssue(
                    id=_lnt_id("redaction_warning", page_id),
                    issue_type="redaction_warning",
                    severity="high",
                    detected_at=now,
                    scope={"pages": [page_id]},
                    summary=f"Page '{slug}' body contains a [REDACTED: placeholder — possible PII exposure.",
                    suggested_action={
                        "kind": "redact",
                        "rationale": "Replace the placeholder with generic text or remove the sensitive passage.",
                    },
                    page_slug=slug,
                )
            )

        # Check: missing required sections (summary pages only) ───────────────
        if page.kind == "summary":
            missing = [s for s in _SUMMARY_REQUIRED_SECTIONS if s not in page.body]
            if missing:
                issues.append(
                    LintIssue(
                        id=_lnt_id("schema_invalid", "missing_sections", page_id),
                        issue_type="schema_invalid",
                        severity="medium",
                        detected_at=now,
                        scope={"pages": [page_id]},
                        summary=(
                            f"Summary page '{slug}' is missing required sections: "
                            + ", ".join(missing)
                        )[:500],
                        suggested_action={
                            "kind": "update_claim",
                            "rationale": "Add the missing sections to conform to the summary-page template.",
                        },
                        page_slug=slug,
                    )
                )

    return issues
