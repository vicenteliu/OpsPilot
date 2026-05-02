"""ID utilities matching the OpsPilot spec.

Two ID flavors live across the 7 spec dirs:

* **ULID-prefixed** (time-ordered, 26-char Crockford body)::

    sess_  run_  itr_  fb_  q_  act_

* **Content-addressed** (sha256 prefix, 8 or 16 hex chars)::

    8-hex  : chk_  doc_  fix_  mem_  var_  lnt_  wpg_  wlk_
    16-hex : art_  skl_

The Crockford alphabet excludes the letters ``I L O U`` (matches every
ULID schema regex used in the spec: ``[0-9A-HJKMNP-TV-Z]{26}``).
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

from ulid import ULID

# Pattern aligning with every *.schema.json that constrains ULID-shaped ids.
ULID_BODY_PATTERN: Final[str] = r"[0-9A-HJKMNP-TV-Z]{26}"

ULID_PREFIXES: Final[frozenset[str]] = frozenset({"sess", "run", "itr", "fb", "q", "act"})

# Hex length per content-id prefix. Wiki adds wpg_ and wlk_, skills add var_/lnt_, etc.
PREFIX_HEX_LEN: Final[dict[str, int]] = {
    # 8-hex content-addressed
    "chk": 8,  # kb chunk
    "doc": 8,  # kb document
    "fix": 8,  # harness fixture
    "mem": 8,  # mid-term memory record
    "var": 8,  # skill variant
    "lnt": 8,  # wiki lint issue
    "wpg": 8,  # wiki page
    "wlk": 8,  # wiki cross-link
    # 16-hex content-addressed (longer because they index larger artifact spaces)
    "art": 16,  # session artifact
    "skl": 16,  # skill SKILL.md content hash
}


# ──────────────────────────────────────────────────────────────────────────
#  Hashing primitives
# ──────────────────────────────────────────────────────────────────────────


def sha256_hex(content: bytes | str) -> str:
    """Return the full 64-char hex sha256 of *content*.

    Used for ``content_hash: "sha256:<...>"`` fields in many schemas.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def sha8(content: bytes | str) -> str:
    """First 8 chars of ``sha256_hex(content)``."""
    return sha256_hex(content)[:8]


def sha16(content: bytes | str) -> str:
    """First 16 chars of ``sha256_hex(content)``. Used for ``art_`` / ``skl_`` ids."""
    return sha256_hex(content)[:16]


# ──────────────────────────────────────────────────────────────────────────
#  ID generation
# ──────────────────────────────────────────────────────────────────────────


def new_ulid_id(prefix: str) -> str:
    """Generate a new ULID-prefixed id (e.g. ``sess_<26 crockford chars>``)."""
    if prefix not in ULID_PREFIXES:
        msg = f"Unknown ULID prefix '{prefix}'; allowed: {sorted(ULID_PREFIXES)}"
        raise ValueError(msg)
    # python-ulid's ``str(ULID())`` is upper-case Crockford, exactly the spec form.
    return f"{prefix}_{ULID()}"


def new_content_id(prefix: str, content: bytes | str) -> str:
    """Generate a content-addressed id like ``chk_<sha8>`` or ``art_<sha16>``."""
    if prefix not in PREFIX_HEX_LEN:
        msg = f"Unknown content-id prefix '{prefix}'; allowed: {sorted(PREFIX_HEX_LEN)}"
        raise ValueError(msg)
    n = PREFIX_HEX_LEN[prefix]
    return f"{prefix}_{sha256_hex(content)[:n]}"


# ──────────────────────────────────────────────────────────────────────────
#  Validators (no parse, no decode — pure shape checks)
# ──────────────────────────────────────────────────────────────────────────


def is_valid_ulid_id(value: str, expected_prefix: str | None = None) -> bool:
    """Return True iff *value* is shaped like a ULID-prefixed id.

    If *expected_prefix* is given, the prefix must match.
    """
    if not isinstance(value, str) or "_" not in value:
        return False
    prefix, _, body = value.partition("_")
    if expected_prefix is not None and prefix != expected_prefix:
        return False
    if prefix not in ULID_PREFIXES:
        return False
    return bool(re.fullmatch(ULID_BODY_PATTERN, body))


def is_valid_content_id(value: str, expected_prefix: str | None = None) -> bool:
    """Return True iff *value* is shaped like a content-addressed id (sha8/sha16 body)."""
    if not isinstance(value, str) or "_" not in value:
        return False
    prefix, _, body = value.partition("_")
    if expected_prefix is not None and prefix != expected_prefix:
        return False
    if prefix not in PREFIX_HEX_LEN:
        return False
    expected_len = PREFIX_HEX_LEN[prefix]
    if len(body) != expected_len:
        return False
    return all(c in "0123456789abcdef" for c in body)
