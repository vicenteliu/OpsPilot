"""Tests for ``opspilot.memory.markitdown_adapter``."""

from __future__ import annotations

from pathlib import Path

import pytest

from opspilot.memory.markitdown_adapter import (
    AdapterError,
    AdapterResult,
    to_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PDF = REPO_ROOT / "tests" / "fixtures" / "sample.pdf"
SAMPLE_MD = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "kb" / "sop_vpn_zh.md"


# ── Passthrough .md ───────────────────────────────────────────────────


def test_md_passthrough(tmp_path: Path) -> None:
    p = tmp_path / "doc.md"
    p.write_text("# Hello\n\nbody text\n", encoding="utf-8")
    out = to_markdown(p)
    assert isinstance(out, AdapterResult)
    assert out.detected_ext == ".md"
    assert out.converted_via_markitdown is False
    assert out.markdown == "# Hello\n\nbody text\n"
    assert out.title == "Hello"


def test_md_no_h1_title_is_none(tmp_path: Path) -> None:
    p = tmp_path / "doc.md"
    p.write_text("just paragraph text, no headings\n", encoding="utf-8")
    out = to_markdown(p)
    assert out.title is None


def test_markdown_alt_ext_passthrough(tmp_path: Path) -> None:
    p = tmp_path / "doc.markdown"
    p.write_text("# Title\n\nbody\n", encoding="utf-8")
    out = to_markdown(p)
    assert out.detected_ext == ".markdown"
    assert out.converted_via_markitdown is False


# ── markitdown for binary formats ─────────────────────────────────────


def test_pdf_converts_via_markitdown() -> None:
    out = to_markdown(SAMPLE_PDF)
    assert out.detected_ext == ".pdf"
    assert out.converted_via_markitdown is True
    assert out.source_size_bytes > 1000
    # Anchor on a couple of fixture-known keywords that markitdown
    # extracts from the reportlab-built PDF.
    assert "OpsPilot" in out.markdown
    assert "ingestion" in out.markdown.lower()


def test_existing_zh_md_round_trip() -> None:
    """Sanity check that the production-shape Chinese .md file works."""
    out = to_markdown(SAMPLE_MD)
    assert out.detected_ext == ".md"
    assert "VPN" in out.markdown


# ── Error paths ───────────────────────────────────────────────────────


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    p = tmp_path / "code.py"
    p.write_text("print('hi')\n", encoding="utf-8")
    with pytest.raises(AdapterError, match="unsupported"):
        to_markdown(p)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(AdapterError, match="not a file"):
        to_markdown(tmp_path / "does-not-exist.md")


def test_magic_mismatch_raises(tmp_path: Path) -> None:
    """A file ending in .pdf but lacking the %PDF- prefix should fail."""
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"this is not a pdf, it's just plain text\n")
    with pytest.raises(AdapterError, match="magic bytes"):
        to_markdown(fake)


def test_magic_byte_check_skipped_for_text_formats(tmp_path: Path) -> None:
    """Text/CSV/HTML have no magic-byte requirement; should pass through."""
    p = tmp_path / "data.csv"
    p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    out = to_markdown(p)
    # markitdown happily consumes csv; should not raise.
    assert out.detected_ext == ".csv"
    assert out.converted_via_markitdown is True


def test_pdf_with_empty_extraction_raises(tmp_path: Path) -> None:
    """A valid PDF magic but markitdown returning '' — surfaced as error."""
    # Make a tiny "PDF" that markitdown will try to parse but get nothing
    # useful from. We use the canonical 1-byte PDF for this — invalid but
    # passes magic check and yields empty content.
    bad = tmp_path / "empty.pdf"
    bad.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(AdapterError):
        to_markdown(bad)
