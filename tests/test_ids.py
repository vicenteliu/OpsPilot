"""Unit tests for ``opspilot.ids``."""

from __future__ import annotations

import pytest

from opspilot.ids import (
    PREFIX_HEX_LEN,
    ULID_PREFIXES,
    is_valid_content_id,
    is_valid_ulid_id,
    new_content_id,
    new_ulid_id,
    sha8,
    sha16,
    sha256_hex,
)


class TestSha:
    def test_sha8_length(self) -> None:
        assert len(sha8("hello")) == 8

    def test_sha16_length(self) -> None:
        assert len(sha16("hello")) == 16

    def test_sha256_full_length_and_charset(self) -> None:
        h = sha256_hex("hello")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_str_and_bytes_equivalent(self) -> None:
        assert sha8("hello") == sha8(b"hello")
        assert sha256_hex("x") == sha256_hex(b"x")

    def test_deterministic(self) -> None:
        assert sha8("a") == sha8("a")
        assert sha8("a") != sha8("b")
        assert sha16("a") == sha16("a")


class TestNewContentId:
    @pytest.mark.parametrize("prefix", sorted(PREFIX_HEX_LEN))
    def test_format_and_validate_roundtrip(self, prefix: str) -> None:
        ident = new_content_id(prefix, b"some content")
        assert ident.startswith(f"{prefix}_")
        assert is_valid_content_id(ident, expected_prefix=prefix)

    def test_8_vs_16_hex_bodies(self) -> None:
        assert len(new_content_id("chk", b"x").split("_", 1)[1]) == 8
        assert len(new_content_id("art", b"x").split("_", 1)[1]) == 16

    def test_unknown_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown content-id prefix"):
            new_content_id("foo", b"content")


class TestNewUlidId:
    @pytest.mark.parametrize("prefix", sorted(ULID_PREFIXES))
    def test_format_and_validate_roundtrip(self, prefix: str) -> None:
        ident = new_ulid_id(prefix)
        assert ident.startswith(f"{prefix}_")
        assert is_valid_ulid_id(ident, expected_prefix=prefix)

    def test_uniqueness(self) -> None:
        ids = {new_ulid_id("sess") for _ in range(100)}
        assert len(ids) == 100

    def test_crockford_alphabet_excludes_iluo(self) -> None:
        forbidden = set("ILOU")
        for _ in range(50):
            body = new_ulid_id("sess").split("_", 1)[1]
            assert not (set(body) & forbidden), f"forbidden char in {body!r}"

    def test_unknown_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown ULID prefix"):
            new_ulid_id("foo")


class TestValidatorsAgainstSpecExamples:
    """Validate IDs that appear verbatim in the spec / examples/ dirs."""

    @pytest.mark.parametrize(
        "value,prefix",
        [
            ("sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0", "sess"),
            ("run_01J0Z9ZQXK7M6P3F0XK5K7C5RR", "run"),
            ("itr_01K2B0BRYN8P8R5H2YJ7M9E7N0", "itr"),
            ("act_01J0Z9ZQXK7M6P3F0XK5K7C5KA", "act"),
            ("q_01J0Z9ZQXK7M6P3F0XK5K7C5K1", "q"),
        ],
    )
    def test_valid_ulid_examples(self, value: str, prefix: str) -> None:
        assert is_valid_ulid_id(value, prefix)

    @pytest.mark.parametrize(
        "value,prefix",
        [
            ("doc_88a277cf", "doc"),
            ("chk_0cf89826", "chk"),
            ("var_9930d615", "var"),
            ("fix_a1b2c3d4", "fix"),
            ("art_75fa2fb140c268a4", "art"),  # 16-hex
        ],
    )
    def test_valid_content_examples(self, value: str, prefix: str) -> None:
        assert is_valid_content_id(value, prefix)

    def test_invalid_ulid_with_forbidden_char(self) -> None:
        # 'I' is not in Crockford alphabet
        assert not is_valid_ulid_id("sess_01I0Z9ZQXK7M6P3F0XK5K7C5K0", "sess")

    def test_invalid_ulid_wrong_length(self) -> None:
        assert not is_valid_ulid_id("sess_01J0Z9ZQXK", "sess")

    def test_invalid_ulid_wrong_prefix(self) -> None:
        assert not is_valid_ulid_id("foo_01J0Z9ZQXK7M6P3F0XK5K7C5K0", "sess")

    def test_invalid_content_id_wrong_length(self) -> None:
        # art_ requires 16 hex; this gives 8 -> fail
        assert not is_valid_content_id("art_88a277cf", "art")
        # doc_ requires 8; 6 -> fail
        assert not is_valid_content_id("doc_88a277", "doc")

    def test_invalid_content_id_non_hex(self) -> None:
        assert not is_valid_content_id("doc_zzzzzzzz", "doc")

    def test_invalid_content_id_wrong_prefix(self) -> None:
        assert not is_valid_content_id("doc_88a277cf", "chk")

    def test_non_string_inputs_safe(self) -> None:
        assert not is_valid_ulid_id(None)  # type: ignore[arg-type]
        assert not is_valid_content_id(123)  # type: ignore[arg-type]
