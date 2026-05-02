"""Unit tests for ``opspilot.timeutil``."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from opspilot.timeutil import UTC, now_rfc3339, now_rfc3339_seconds, parse_rfc3339

# Sanity check: our re-exported UTC matches the stdlib timezone.utc.
# Use timezone.utc explicitly to verify identity with the legacy alias —
# `datetime.UTC` (3.11+) and `timezone.utc` are the same singleton.
assert UTC is timezone.utc  # noqa: UP017


def test_now_rfc3339_format() -> None:
    s = now_rfc3339()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", s), s


def test_now_rfc3339_seconds_format() -> None:
    s = now_rfc3339_seconds()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s), s


def test_parse_rfc3339_z_suffix() -> None:
    dt = parse_rfc3339("2026-05-01T10:00:00Z")
    assert dt.tzinfo == UTC
    assert dt == datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)


def test_parse_rfc3339_offset_suffix() -> None:
    dt = parse_rfc3339("2026-05-01T10:00:00+00:00")
    assert dt == datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)


def test_parse_rfc3339_with_milliseconds() -> None:
    dt = parse_rfc3339("2026-05-01T10:00:00.123Z")
    assert dt.microsecond == 123_000


def test_parse_rfc3339_normalizes_to_utc() -> None:
    dt = parse_rfc3339("2026-05-01T18:00:00+08:00")
    assert dt.tzinfo == UTC
    assert dt.hour == 10  # 18:00 +08:00 == 10:00Z


def test_parse_rfc3339_naive_rejected() -> None:
    # Python's fromisoformat happily parses naive strings; we must reject.
    with pytest.raises(ValueError, match="must be timezone-aware"):
        parse_rfc3339("2026-05-01T10:00:00")


def test_round_trip_now_to_parse() -> None:
    s = now_rfc3339()
    dt = parse_rfc3339(s)
    assert dt.tzinfo == UTC
