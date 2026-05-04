"""BPE-ish token counter (PR-18).

Algorithm: ASCII alphanumeric runs = 1 token; ASCII whitespace = 0 tokens;
every other character (ASCII punctuation, any Unicode code point) = 1 token.

This is a practical approximation of CL100K / GPT-2 BPE tokenization:
- English prose: ~1 token per 4 chars (words cluster into single tokens)
- CJK text: ~1 token per character (each ideograph is typically 1-2 tokens)
- Mixed: interpolates naturally

The Rust extension (opspilot_tokenizer) implements the same algorithm and
is dispatched automatically when installed.
"""

from __future__ import annotations

import re

# ASCII flag so that \s matches only [ \t\n\r\f\v], not Unicode whitespace.
# Matches Python token boundaries: alphanumeric groups or single non-whitespace.
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[^\s]", re.ASCII)


def _py_count_tokens(text: str) -> int:
    """Pure-Python implementation (reference / fallback)."""
    return max(1, len(_TOKEN_RE.findall(text)))


# ── Rust-accelerated dispatch ─────────────────────────────────────────────

try:
    from opspilot_tokenizer import count_tokens as _rs_count_tokens

    _HAS_RUST_TOKENIZER = True
except ImportError:
    _HAS_RUST_TOKENIZER = False


def count_tokens(text: str) -> int:
    """Count approximate BPE-style tokens.

    Dispatches to the Rust extension when available (≥5x faster); falls back
    to the pure-Python implementation otherwise.
    """
    if _HAS_RUST_TOKENIZER:
        return _rs_count_tokens(text)
    return _py_count_tokens(text)
