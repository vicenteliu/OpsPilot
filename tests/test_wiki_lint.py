"""Tests for the wiki lint engine (PR-23)."""

from __future__ import annotations

from pathlib import Path

from opspilot.wiki.lint import LintIssue, lint_wiki
from opspilot.wiki.page import WikiPage, write_page

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_page(
    slug: str,
    *,
    kind: str = "summary",
    body: str = "## TL;DR\nFoo.\n## Key claims\n1. Bar.\n## Sources\n1. Baz.",
    lifecycle_state: str = "live",
    inbound_link_count: int = 0,
) -> WikiPage:
    from opspilot.timeutil import now_rfc3339
    from opspilot.wiki.page import make_page_id

    now = now_rfc3339()
    return WikiPage(
        page_id=make_page_id(slug, body),
        slug=slug,
        kind=kind,
        title=slug.replace("-", " ").title(),
        summary=f"Summary of {slug}.",
        namespace="opspilot:public-kb",
        classification="internal",
        language="en",
        version="1.0.0",
        created_at=now,
        updated_at=now,
        derived_from={"sources": [], "parent_pages": []},
        outbound_links=[],
        inbound_link_count=inbound_link_count,
        redacted=True,
        redaction_rules_version="1.0.0",
        lifecycle_state=lifecycle_state,
        owner="test@opspilot",
        body=body,
    )


def _write(wiki_root: Path, page: WikiPage, kind_subdir: str = "") -> None:
    sub = kind_subdir or page.kind
    path = wiki_root / "pages" / sub / f"{page.slug}.md"
    write_page(page, path)


# ── Empty / missing wiki ───────────────────────────────────────────────────────


class TestEmptyWiki:
    def test_no_pages_dir_returns_empty(self, tmp_path: Path) -> None:
        assert lint_wiki(tmp_path) == []

    def test_empty_pages_dir_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "pages").mkdir()
        assert lint_wiki(tmp_path) == []


# ── Orphan check ──────────────────────────────────────────────────────────────


class TestOrphan:
    def test_single_page_is_orphan(self, tmp_path: Path) -> None:
        _write(tmp_path, _make_page("my-page"))
        issues = lint_wiki(tmp_path)
        orphans = [i for i in issues if i.issue_type == "orphan"]
        assert len(orphans) == 1
        assert orphans[0].page_slug == "my-page"

    def test_page_with_inbound_link_not_orphan(self, tmp_path: Path) -> None:
        page_a = _make_page("alpha")
        page_b = _make_page(
            "beta", body="## TL;DR\nSee [[alpha]].\n## Key claims\n1. x.\n## Sources\n1. y."
        )
        _write(tmp_path, page_a)
        _write(tmp_path, page_b)
        issues = lint_wiki(tmp_path)
        orphans = [i for i in issues if i.issue_type == "orphan"]
        # beta links to alpha → alpha is not orphan; beta has no inbound
        orphan_slugs = {i.page_slug for i in orphans}
        assert "alpha" not in orphan_slugs
        assert "beta" in orphan_slugs

    def test_archived_page_not_flagged_as_orphan(self, tmp_path: Path) -> None:
        _write(tmp_path, _make_page("old-page", lifecycle_state="archived"))
        issues = lint_wiki(tmp_path)
        orphans = [i for i in issues if i.issue_type == "orphan"]
        assert not orphans


# ── Broken link check ─────────────────────────────────────────────────────────


class TestBrokenLink:
    def test_link_to_missing_slug(self, tmp_path: Path) -> None:
        body = "## TL;DR\nSee [[ghost-page]].\n## Key claims\n1. x.\n## Sources\n1. y."
        _write(tmp_path, _make_page("source-page", body=body))
        issues = lint_wiki(tmp_path)
        broken = [i for i in issues if i.issue_type == "broken_link"]
        assert len(broken) == 1
        assert "ghost-page" in broken[0].summary

    def test_link_to_existing_slug_ok(self, tmp_path: Path) -> None:
        _write(tmp_path, _make_page("target-page"))
        body = "## TL;DR\nSee [[target-page]].\n## Key claims\n1. x.\n## Sources\n1. y."
        _write(tmp_path, _make_page("source-page", body=body))
        issues = lint_wiki(tmp_path)
        broken = [i for i in issues if i.issue_type == "broken_link"]
        assert not broken

    def test_duplicate_broken_link_emitted_once(self, tmp_path: Path) -> None:
        body = (
            "## TL;DR\nSee [[ghost]] and [[ghost]] again.\n## Key claims\n1. x.\n## Sources\n1. y."
        )
        _write(tmp_path, _make_page("src", body=body))
        issues = lint_wiki(tmp_path)
        broken = [i for i in issues if i.issue_type == "broken_link"]
        assert len(broken) == 1


# ── Redaction warning check ───────────────────────────────────────────────────


class TestRedactionWarning:
    def test_redacted_placeholder_in_body(self, tmp_path: Path) -> None:
        body = "## TL;DR\nSee [REDACTED: name].\n## Key claims\n1. x.\n## Sources\n1. y."
        _write(tmp_path, _make_page("leaky-page", body=body))
        issues = lint_wiki(tmp_path)
        warn = [i for i in issues if i.issue_type == "redaction_warning"]
        assert len(warn) == 1
        assert warn[0].severity == "high"

    def test_clean_body_no_warning(self, tmp_path: Path) -> None:
        _write(tmp_path, _make_page("clean-page"))
        issues = lint_wiki(tmp_path)
        assert not [i for i in issues if i.issue_type == "redaction_warning"]


# ── Missing sections check ────────────────────────────────────────────────────


class TestMissingSections:
    def test_summary_page_missing_tldr(self, tmp_path: Path) -> None:
        body = "## Key claims\n1. x.\n## Sources\n1. y."
        _write(tmp_path, _make_page("broken-summary", kind="summary", body=body))
        issues = lint_wiki(tmp_path)
        invalid = [i for i in issues if i.issue_type == "schema_invalid"]
        assert any("TL;DR" in i.summary for i in invalid)

    def test_summary_page_missing_sources(self, tmp_path: Path) -> None:
        body = "## TL;DR\nFoo.\n## Key claims\n1. x."
        _write(tmp_path, _make_page("no-sources", kind="summary", body=body))
        issues = lint_wiki(tmp_path)
        invalid = [i for i in issues if i.issue_type == "schema_invalid"]
        assert any("Sources" in i.summary for i in invalid)

    def test_non_summary_kind_no_section_check(self, tmp_path: Path) -> None:
        body = "## Definition\nSomething.\n## Why it matters\nBecause."
        _write(tmp_path, _make_page("concept-page", kind="concept", body=body))
        issues = lint_wiki(tmp_path)
        invalid = [i for i in issues if i.issue_type == "schema_invalid"]
        assert not invalid


# ── Schema invalid / parse error ─────────────────────────────────────────────


class TestParseError:
    def test_malformed_frontmatter(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "pages" / "summary" / "broken.md"
        bad_file.parent.mkdir(parents=True)
        bad_file.write_text("not a valid wiki page\n", encoding="utf-8")
        issues = lint_wiki(tmp_path)
        invalid = [i for i in issues if i.issue_type == "schema_invalid"]
        assert len(invalid) >= 1


# ── LintIssue data model ──────────────────────────────────────────────────────


class TestLintIssue:
    def test_to_dict_excludes_page_slug(self) -> None:
        issue = LintIssue(
            id="lnt_abcd1234",
            issue_type="orphan",
            severity="medium",
            detected_at="2026-05-04T00:00:00Z",
            scope={"pages": ["wpg_abcd1234"]},
            summary="Page 'foo' has no inbound links.",
            suggested_action={"kind": "add_cross_ref", "rationale": "link it"},
            page_slug="foo",
        )
        d = issue.to_dict()
        assert "page_slug" not in d
        assert d["issue_type"] == "orphan"
        assert d["scope"]["pages"] == ["wpg_abcd1234"]

    def test_lnt_id_is_deterministic(self, tmp_path: Path) -> None:
        _write(tmp_path, _make_page("stable"))
        issues1 = lint_wiki(tmp_path)
        issues2 = lint_wiki(tmp_path)
        ids1 = {i.id for i in issues1}
        ids2 = {i.id for i in issues2}
        assert ids1 == ids2
