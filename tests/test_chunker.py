"""Tests for ``opspilot.memory.chunker``."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from opspilot.memory.chunker import (
    ChunkConfig,
    _py_chunk_markdown,
    _strip_frontmatter,
    chunk_markdown,
)

try:
    import opspilot_chunker as _rs_mod

    _HAS_RUST = True
except ImportError:
    _HAS_RUST = False

# ──────────────────────────────────────────────────────────────────────────
#  Frontmatter handling
# ──────────────────────────────────────────────────────────────────────────


class TestFrontmatter:
    def test_no_frontmatter(self) -> None:
        text = "# Title\n\nbody\n"
        body, char, line = _strip_frontmatter(text)
        assert body == text
        assert char == 0
        assert line == 1

    def test_simple_frontmatter(self) -> None:
        text = "---\nfoo: 1\n---\n# Title\n\nbody\n"
        body, char, line = _strip_frontmatter(text)
        assert body == "# Title\n\nbody\n"
        # char offset should advance past "---\nfoo: 1\n---\n"
        assert char == len("---\nfoo: 1\n---\n")
        # line: body's first line is line 4 in the original (1-based)
        assert line == 4

    def test_frontmatter_without_closing_fence(self) -> None:
        # Malformed: no closing ``---``. Treat as no frontmatter.
        text = "---\nfoo: 1\nbar: 2\n# Title\n"
        body, char, line = _strip_frontmatter(text)
        assert body == text
        assert char == 0
        assert line == 1


# ──────────────────────────────────────────────────────────────────────────
#  Tiny end-to-end on hand-crafted markdown
# ──────────────────────────────────────────────────────────────────────────


SIMPLE_DOC = textwrap.dedent(
    """\
    # Title

    intro paragraph.

    ## Section A

    body of A goes here, more than a few words to be content-bearing.

    ## Section B

    body of B is also non-trivial in length.
    """
)


class TestSimple:
    def test_runs_at_all(self) -> None:
        chunks = chunk_markdown(SIMPLE_DOC)
        assert len(chunks) >= 1

    def test_all_chunks_have_valid_offsets(self) -> None:
        chunks = chunk_markdown(SIMPLE_DOC)
        for c in chunks:
            assert c.char_start >= 0
            assert c.char_end > c.char_start
            assert c.char_end <= len(SIMPLE_DOC)
            # content reconstructable from char range
            assert SIMPLE_DOC[c.char_start : c.char_end] == c.content
            # 1-based, monotonic
            assert c.line_start >= 1
            assert c.line_end >= c.line_start

    def test_heading_path_present(self) -> None:
        chunks = chunk_markdown(SIMPLE_DOC)
        # at least one chunk should reference the H1 title
        assert any("Title" in c.heading_path for c in chunks)

    def test_seq_is_sequential(self) -> None:
        chunks = chunk_markdown(SIMPLE_DOC)
        assert [c.seq for c in chunks] == list(range(len(chunks)))

    def test_token_count_positive(self) -> None:
        for c in chunk_markdown(SIMPLE_DOC):
            assert c.token_count > 0


# ──────────────────────────────────────────────────────────────────────────
#  Heading-only block: skipped from chunking, but path is propagated
# ──────────────────────────────────────────────────────────────────────────


HEADING_ONLY_DOC = textwrap.dedent(
    """\
    # Top

    ## Outer

    ### Inner

    inner body
    """
)


class TestHeadingOnly:
    def test_outer_heading_only_skipped(self) -> None:
        chunks = chunk_markdown(HEADING_ONLY_DOC)
        # The "## Outer" section has no body of its own, so it must not
        # become a standalone chunk; but its title must show up in the
        # next chunk's heading_path.
        assert len(chunks) >= 1
        # find the chunk containing "inner body"
        inner = next(c for c in chunks if "inner body" in c.content)
        # heading_path should include Outer
        assert "Outer" in inner.heading_path
        assert "Inner" in inner.heading_path


# ──────────────────────────────────────────────────────────────────────────
#  Spec example: chunk the actual sop_vpn_zh.md file used by other tests
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sop_vpn_zh_text(repo_root: Path) -> str:
    path = repo_root / "examples" / "scn_ticket_summary_zh" / "kb" / "sop_vpn_zh.md"
    if not path.is_file():
        pytest.skip(f"sample missing: {path}")
    return path.read_text(encoding="utf-8")


class TestSpecSampleVpnZh:
    """Smoke-test against the real sample we ship under examples/.

    PR-2 deliberately does not match the sample's hand-curated 3-chunk
    layout byte-for-byte; that's what PR-5 will tune (with a real
    tokenizer). What we DO require:

    * frontmatter is stripped (chunk 0 starts at the H1, line >= 21)
    * at least one chunk contains the key authentication-errors content
    * every chunk's char range reconstructs valid content
    * heading_path tracks the H1
    """

    def test_strips_frontmatter(self, sop_vpn_zh_text: str) -> None:
        chunks = chunk_markdown(sop_vpn_zh_text)
        assert len(chunks) >= 1
        # First chunk's content should not contain frontmatter keys
        assert "schema_version" not in chunks[0].content
        # Body starts at the H1 ``# VPN 故障排查 SOP`` (line 21 in the source)
        assert chunks[0].line_start >= 21

    def test_auth_errors_section_captured(self, sop_vpn_zh_text: str) -> None:
        chunks = chunk_markdown(sop_vpn_zh_text)
        joined = "\n".join(c.content for c in chunks)
        assert "认证错误" in joined
        assert "authentication failed" in joined

    def test_h1_in_first_heading_path(self, sop_vpn_zh_text: str) -> None:
        chunks = chunk_markdown(sop_vpn_zh_text)
        assert chunks[0].heading_path
        assert chunks[0].heading_path[0] == "VPN 故障排查 SOP"

    def test_offsets_reconstruct_content(self, sop_vpn_zh_text: str) -> None:
        for c in chunk_markdown(sop_vpn_zh_text):
            assert sop_vpn_zh_text[c.char_start : c.char_end] == c.content

    def test_token_counts_in_range(self, sop_vpn_zh_text: str) -> None:
        cfg = ChunkConfig()
        for c in chunk_markdown(sop_vpn_zh_text, config=cfg):
            assert c.token_count > 0
            # should not exceed max_size by an unreasonable margin
            assert c.token_count <= cfg.max_size_tokens * 2


# ──────────────────────────────────────────────────────────────────────────
#  ChunkConfig defaults & overrides
# ──────────────────────────────────────────────────────────────────────────


class TestConfig:
    def test_default_config(self) -> None:
        cfg = ChunkConfig()
        assert cfg.target_size_tokens == 512
        assert cfg.max_size_tokens == 1024
        assert cfg.strategy == "headings_then_size"

    def test_smaller_target_yields_more_chunks(self, sop_vpn_zh_text: str) -> None:
        big = chunk_markdown(sop_vpn_zh_text, config=ChunkConfig(target_size_tokens=2000))
        small = chunk_markdown(sop_vpn_zh_text, config=ChunkConfig(target_size_tokens=80))
        assert len(small) >= len(big)


# ──────────────────────────────────────────────────────────────────────────
#  Rust / Python output parity
# ──────────────────────────────────────────────────────────────────────────

PARITY_TEXTS = [
    SIMPLE_DOC,
    HEADING_ONLY_DOC,
    "# Only heading\n",
    "no heading at all\njust text\n",
    "",
    "---\ntitle: Test\n---\n# Body\ncontent\n",
]


@pytest.mark.skipif(not _HAS_RUST, reason="opspilot_chunker Rust extension not installed")
class TestRustParity:
    """Verify Rust chunker output matches Python on every field."""

    @pytest.mark.parametrize("text", PARITY_TEXTS)
    def test_field_by_field(self, text: str) -> None:
        py = _py_chunk_markdown(text)
        rs_raw = _rs_mod.chunk_markdown(text)
        assert len(py) == len(rs_raw), f"chunk count mismatch on: {text[:40]!r}"
        for p, r in zip(py, rs_raw, strict=True):
            assert p.content == r.content, f"content mismatch seq={p.seq}"
            assert p.char_start == r.char_start, f"char_start mismatch seq={p.seq}"
            assert p.char_end == r.char_end, f"char_end mismatch seq={p.seq}"
            assert p.line_start == r.line_start, f"line_start mismatch seq={p.seq}"
            assert p.line_end == r.line_end, f"line_end mismatch seq={p.seq}"
            assert list(p.heading_path) == r.heading_path, f"heading_path mismatch seq={p.seq}"
            assert p.anchor == r.anchor, f"anchor mismatch seq={p.seq}"
            assert p.token_count == r.token_count, f"token_count mismatch seq={p.seq}"

    def test_parity_on_vpn_sop(self, sop_vpn_zh_text: str) -> None:
        py = _py_chunk_markdown(sop_vpn_zh_text)
        rs_raw = _rs_mod.chunk_markdown(sop_vpn_zh_text)
        assert len(py) == len(rs_raw)
        for p, r in zip(py, rs_raw, strict=True):
            assert p.content == r.content
            assert p.char_start == r.char_start
            assert p.char_end == r.char_end
