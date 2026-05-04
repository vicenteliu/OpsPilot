"""Tests for opspilot.memory.tokenizer."""

from __future__ import annotations

from pathlib import Path

import pytest

from opspilot.memory.tokenizer import _py_count_tokens, count_tokens

try:
    import opspilot_tokenizer as _rs_mod

    _HAS_RUST = True
except ImportError:
    _HAS_RUST = False


# ──────────────────────────────────────────────────────────────────────────
#  Python implementation correctness
# ──────────────────────────────────────────────────────────────────────────


class TestPyCountTokens:
    def test_empty_string(self) -> None:
        assert _py_count_tokens("") == 1  # max(1, 0)

    def test_whitespace_only(self) -> None:
        assert _py_count_tokens("   \t\n") == 1  # max(1, 0)

    def test_single_word(self) -> None:
        assert _py_count_tokens("hello") == 1

    def test_two_words(self) -> None:
        assert _py_count_tokens("hello world") == 2

    def test_word_with_punctuation(self) -> None:
        # "hello" + "," + "world" + "!"
        assert _py_count_tokens("hello,world!") == 4

    def test_number_word(self) -> None:
        # "CPU" + "2" grouped: "CPU2" is one alphanumeric run
        assert _py_count_tokens("CPU2") == 1

    def test_cjk_chars(self) -> None:
        # Each CJK char is its own token
        assert _py_count_tokens("你好世界") == 4

    def test_mixed_cjk_ascii(self) -> None:
        # "CPU" = 1, "的" = 1, "性" = 1, "能" = 1
        assert _py_count_tokens("CPU的性能") == 4

    def test_cjk_with_spaces(self) -> None:
        # Space is skipped, each CJK char = 1
        assert _py_count_tokens("你 好") == 2

    def test_ascii_sentence(self) -> None:
        # "The" + "quick" + "brown" + "fox"
        assert _py_count_tokens("The quick brown fox") == 4

    def test_numbers(self) -> None:
        # "123" is one alphanumeric run
        assert _py_count_tokens("123") == 1

    def test_number_plus_word(self) -> None:
        # "3" + "." + "14" — not adjacent alphanumeric runs (period in between)
        assert _py_count_tokens("3.14") == 3

    def test_newlines_skipped(self) -> None:
        assert _py_count_tokens("a\nb") == 2

    def test_emoji(self) -> None:
        # Each emoji = 1 token (non-ASCII, non-whitespace)
        assert _py_count_tokens("hello 🎉") == 2

    def test_result_positive(self) -> None:
        for text in ["", " ", "\n", "a", "hello", "你好", "hello world 你好"]:
            assert count_tokens(text) >= 1


# ──────────────────────────────────────────────────────────────────────────
#  Rust / Python parity
# ──────────────────────────────────────────────────────────────────────────

PARITY_TEXTS = [
    "",
    " ",
    "hello",
    "hello world",
    "hello,world!",
    "你好世界",
    "CPU的性能",
    "The quick brown fox jumps over the lazy dog.",
    "3.14 is π",
    "hello 🎉 world",
    "   \t\n  ",
    "a1b2c3",
    "---\nfoo: bar\n---\n",
]


@pytest.mark.skipif(not _HAS_RUST, reason="opspilot_tokenizer not installed")
class TestRustParity:
    @pytest.mark.parametrize("text", PARITY_TEXTS)
    def test_matches_python(self, text: str) -> None:
        py = _py_count_tokens(text)
        rs = _rs_mod.count_tokens(text)
        assert py == rs, f"mismatch on {text!r}: py={py} rs={rs}"

    def test_parity_on_vpn_sop(self, repo_root: Path) -> None:
        path = repo_root / "examples" / "scn_ticket_summary_zh" / "kb" / "sop_vpn_zh.md"
        if not path.is_file():
            pytest.skip(f"sample missing: {path}")
        text = path.read_text(encoding="utf-8")
        assert _py_count_tokens(text) == _rs_mod.count_tokens(text)
