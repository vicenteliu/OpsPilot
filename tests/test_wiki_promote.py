"""Tests for wiki promote engine (PR-25)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opspilot.wiki.page import WikiPage, make_page_id, write_page
from opspilot.wiki.promote import PromoteConfig, PromoteError, _bump_minor, promote_page

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_page(
    tmp_path: Path,
    *,
    slug: str = "test-slug",
    kind: str = "synthesis",
    lifecycle_state: str = "draft",
    version: str = "1.0.0",
    body: str = "## Thesis\nSome content.\n\n## Changelog\n- v1.0.0 (2026-01-01): initial\n",
) -> Path:
    wiki_root = tmp_path / "wiki"
    page_dir = wiki_root / "pages" / kind
    page_dir.mkdir(parents=True, exist_ok=True)
    page_path = page_dir / f"{slug}.md"

    page = WikiPage(
        page_id=make_page_id(slug, body),
        slug=slug,
        kind=kind,
        title="Test Page",
        summary="A test page.",
        namespace="opspilot:public-kb",
        classification="internal",
        language="en",
        version=version,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        derived_from={"sources": [], "parent_pages": []},
        outbound_links=[],
        inbound_link_count=0,
        redacted=True,
        redaction_rules_version="1.0.0",
        lifecycle_state=lifecycle_state,
        owner="wiki-maintainer@opspilot",
        body=body,
    )
    write_page(page, page_path)
    return page_path


def _cfg(tmp_path: Path, target_state: str = "live") -> PromoteConfig:
    return PromoteConfig(wiki_root=tmp_path / "wiki", target_state=target_state)


# ── _bump_minor ────────────────────────────────────────────────────────────────


class TestBumpMinor:
    def test_basic(self) -> None:
        assert _bump_minor("1.0.0") == "1.1.0"

    def test_nonzero_minor(self) -> None:
        assert _bump_minor("2.3.1") == "2.4.0"

    def test_invalid_returns_as_is(self) -> None:
        assert _bump_minor("not-semver") == "not-semver"


# ── promote_page: happy paths ──────────────────────────────────────────────────


class TestPromotePage:
    def test_promotes_draft_to_live(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="draft")
        result = promote_page("test-slug", _cfg(tmp_path))

        assert not result.skipped
        assert result.old_state == "draft"
        assert result.new_state == "live"

    def test_updates_lifecycle_state_in_file(self, tmp_path: Path) -> None:
        page_path = _make_page(tmp_path, lifecycle_state="draft")
        promote_page("test-slug", _cfg(tmp_path))

        content = page_path.read_text(encoding="utf-8")
        assert "lifecycle_state: live" in content

    def test_bumps_version(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="draft", version="1.0.0")
        result = promote_page("test-slug", _cfg(tmp_path))

        assert result.new_version == "1.1.0"

    def test_appends_changelog_entry(self, tmp_path: Path) -> None:
        page_path = _make_page(tmp_path, lifecycle_state="draft")
        promote_page("test-slug", _cfg(tmp_path))

        content = page_path.read_text(encoding="utf-8")
        assert "promoted to live" in content
        assert "v1.1.0" in content

    def test_updates_updated_at(self, tmp_path: Path) -> None:
        page_path = _make_page(tmp_path, lifecycle_state="draft")
        promote_page("test-slug", _cfg(tmp_path))

        from opspilot.wiki.page import read_page

        page = read_page(page_path)
        assert page.updated_at != "2026-01-01T00:00:00Z"

    def test_updates_index(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="draft")
        promote_page("test-slug", _cfg(tmp_path))

        index = (tmp_path / "wiki" / "index.md").read_text(encoding="utf-8")
        assert "test-slug" in index

    def test_appends_log(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="draft")
        promote_page("test-slug", _cfg(tmp_path))

        log = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
        assert "promote" in log
        assert "test-slug" in log

    def test_promotes_draft_to_reviewed(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="draft")
        result = promote_page("test-slug", _cfg(tmp_path, target_state="reviewed"))

        assert result.new_state == "reviewed"

    def test_promotes_reviewed_to_live(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="reviewed")
        result = promote_page("test-slug", _cfg(tmp_path, target_state="live"))

        assert result.new_state == "live"

    def test_promotes_live_to_stale(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="live")
        result = promote_page("test-slug", _cfg(tmp_path, target_state="stale"))

        assert result.new_state == "stale"

    def test_body_without_changelog_section_gets_one(self, tmp_path: Path) -> None:
        page_path = _make_page(tmp_path, lifecycle_state="draft", body="## Thesis\nContent.\n")
        promote_page("test-slug", _cfg(tmp_path))

        content = page_path.read_text(encoding="utf-8")
        assert "## Changelog" in content
        assert "promoted to live" in content


# ── promote_page: skip paths ───────────────────────────────────────────────────


class TestPromoteSkip:
    def test_slug_not_found_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "wiki" / "pages" / "synthesis").mkdir(parents=True)
        result = promote_page("nonexistent-slug", _cfg(tmp_path))

        assert result.skipped
        assert "not found" in result.skip_reason

    def test_already_at_target_skipped(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="live")
        result = promote_page("test-slug", _cfg(tmp_path, target_state="live"))

        assert result.skipped
        assert "already" in result.skip_reason


# ── promote_page: error paths ──────────────────────────────────────────────────


class TestPromoteErrors:
    def test_invalid_transition_raises(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="draft")
        with pytest.raises(PromoteError, match="Invalid transition"):
            promote_page("test-slug", _cfg(tmp_path, target_state="archived"))

    def test_unknown_target_state_raises(self, tmp_path: Path) -> None:
        _make_page(tmp_path, lifecycle_state="draft")
        with pytest.raises(PromoteError, match="Unknown target state"):
            promote_page("test-slug", _cfg(tmp_path, target_state="published"))
