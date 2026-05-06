"""Tests for ingestion._normalize_date and _extract_valid_from."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from opspilot.memory.ingestion import _extract_valid_from, _normalize_date

# ISO8601 timestamp pattern — accepts optional fractional seconds
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _is_iso(s: str) -> bool:
    return bool(_ISO_RE.match(s))


# ── _normalize_date ───────────────────────────────────────────────────


def test_normalize_date_iso_date() -> None:
    assert _normalize_date("2026-01-15") == "2026-01-15T00:00:00Z"


def test_normalize_date_iso_date_with_whitespace() -> None:
    assert _normalize_date("  2026-01-15  ") == "2026-01-15T00:00:00Z"


def test_normalize_date_slash_ymd() -> None:
    assert _normalize_date("2026/01/15") == "2026-01-15T00:00:00Z"


def test_normalize_date_slash_dmy() -> None:
    # European format DD/MM/YYYY
    assert _normalize_date("15/01/2026") == "2026-01-15T00:00:00Z"


def test_normalize_date_slash_mdy() -> None:
    # US format MM/DD/YYYY (only reached when day > 12 disambiguates)
    assert _normalize_date("01/20/2026") == "2026-01-20T00:00:00Z"


def test_normalize_date_iso_datetime_with_seconds() -> None:
    assert _normalize_date("2026-01-15T10:30:45") == "2026-01-15T10:30:45Z"


def test_normalize_date_iso_datetime_with_timezone_suffix() -> None:
    # Truncate to seconds, keep the date+time part
    result = _normalize_date("2026-01-15T10:30:45+08:00")
    assert result == "2026-01-15T10:30:45Z"


def test_normalize_date_unrecognized_returns_as_is() -> None:
    val = "January 2026"
    assert _normalize_date(val) == val


# ── _extract_valid_from — frontmatter ─────────────────────────────────

# A fake path with no date in the stem and non-existent on disk so
# we don't accidentally trigger mtime fallback during frontmatter tests.
_FAKE_PATH = Path("/nonexistent/no-date-here.md")


def _fm(content: str) -> str:
    """Wrap content in YAML frontmatter block."""
    return f"---\n{content}\n---\n\nBody text."


def test_frontmatter_date_key() -> None:
    md = _fm("date: 2026-03-10")
    result = _extract_valid_from(_FAKE_PATH, md)
    assert result == "2026-03-10T00:00:00Z"


def test_frontmatter_valid_from_key() -> None:
    md = _fm("valid_from: 2026-05-01")
    result = _extract_valid_from(_FAKE_PATH, md)
    assert result == "2026-05-01T00:00:00Z"


def test_frontmatter_updated_key() -> None:
    md = _fm("updated: 2026-04-20")
    result = _extract_valid_from(_FAKE_PATH, md)
    assert result == "2026-04-20T00:00:00Z"


def test_frontmatter_last_updated_key() -> None:
    md = _fm("last_updated: 2026-04-01")
    result = _extract_valid_from(_FAKE_PATH, md)
    assert result == "2026-04-01T00:00:00Z"


def test_frontmatter_created_key() -> None:
    md = _fm("created: 2026-02-14")
    result = _extract_valid_from(_FAKE_PATH, md)
    assert result == "2026-02-14T00:00:00Z"


def test_frontmatter_date_takes_priority_over_created() -> None:
    # "date" is checked before "created" in the key order
    md = _fm("date: 2026-03-01\ncreated: 2026-01-01")
    result = _extract_valid_from(_FAKE_PATH, md)
    assert result == "2026-03-01T00:00:00Z"


def test_frontmatter_slash_date_format() -> None:
    md = _fm("date: 2026/05/06")
    result = _extract_valid_from(_FAKE_PATH, md)
    assert result == "2026-05-06T00:00:00Z"


def test_frontmatter_no_recognized_key_falls_through(tmp_path: Path) -> None:
    # Frontmatter has no date key → should fall through to filename check
    doc = tmp_path / "2026-01-20-guide.md"
    doc.write_text("---\nauthor: Alice\n---\nBody.")
    result = _extract_valid_from(doc, doc.read_text())
    assert result == "2026-01-20T00:00:00Z"


def test_frontmatter_invalid_yaml_falls_through(tmp_path: Path) -> None:
    # Malformed YAML → exception swallowed, falls through to filename
    doc = tmp_path / "2026-03-15-broken.md"
    doc.write_text("---\n: : invalid yaml :\n---\nBody.")
    result = _extract_valid_from(doc, doc.read_text())
    assert result == "2026-03-15T00:00:00Z"


def test_frontmatter_missing_closing_marker_falls_through(tmp_path: Path) -> None:
    # No closing `---` → not treated as frontmatter
    doc = tmp_path / "2026-02-28-no-close.md"
    doc.write_text("---\ndate: 2026-01-01\nBody without closing marker.")
    result = _extract_valid_from(doc, doc.read_text())
    assert result == "2026-02-28T00:00:00Z"


# ── _extract_valid_from — filename patterns ────────────────────────────


def test_filename_yyyy_mm_dd_dashes(tmp_path: Path) -> None:
    doc = tmp_path / "2026-05-06-policy.md"
    doc.write_text("No frontmatter.")
    result = _extract_valid_from(doc, doc.read_text())
    assert result == "2026-05-06T00:00:00Z"


def test_filename_yyyy_mm_dd_underscores(tmp_path: Path) -> None:
    doc = tmp_path / "2026_01_15_sop_vpn.md"
    doc.write_text("No frontmatter.")
    result = _extract_valid_from(doc, doc.read_text())
    assert result == "2026-01-15T00:00:00Z"


def test_filename_date_embedded_in_longer_name(tmp_path: Path) -> None:
    doc = tmp_path / "it-guide-2026-03-20-v2.md"
    doc.write_text("No frontmatter.")
    result = _extract_valid_from(doc, doc.read_text())
    assert result == "2026-03-20T00:00:00Z"


def test_filename_no_date_falls_through_to_mtime(tmp_path: Path) -> None:
    doc = tmp_path / "no-date-in-name.md"
    doc.write_text("No frontmatter.")
    result = _extract_valid_from(doc, doc.read_text())
    assert _is_iso(result)
    # result should match the actual mtime of the file
    from datetime import datetime, timezone
    expected = datetime.fromtimestamp(doc.stat().st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert result == expected


# ── _extract_valid_from — mtime fallback ──────────────────────────────


def test_mtime_fallback_returns_iso(tmp_path: Path) -> None:
    doc = tmp_path / "plain.md"
    doc.write_text("No frontmatter, no date in name.")
    result = _extract_valid_from(doc, doc.read_text())
    assert _is_iso(result)


def test_mtime_fallback_matches_actual_mtime(tmp_path: Path) -> None:
    doc = tmp_path / "plain.md"
    doc.write_text("content")
    from datetime import datetime, timezone
    expected = datetime.fromtimestamp(doc.stat().st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    result = _extract_valid_from(doc, doc.read_text())
    assert result == expected


# ── _extract_valid_from — now() fallback ──────────────────────────────


def test_now_fallback_for_nonexistent_path() -> None:
    # Path doesn't exist and stem has no date → falls all the way to now()
    ghost = Path("/nonexistent/plain-no-date.md")
    before = time.time()
    result = _extract_valid_from(ghost, "No frontmatter.")
    after = time.time()
    assert _is_iso(result)
    from datetime import datetime, timezone
    # Strip optional fractional seconds before parsing
    result_secs = result.rstrip("Z").split(".")[0] + "Z"
    ts = datetime.strptime(result_secs, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    assert before - 2 <= ts <= after + 2
