"""RFC3339 / UTC timestamp helpers.

OpsPilot strongly requires RFC3339 + UTC across every audit/trace/log surface
(see e.g. session/SPEC.md §9). Centralizing the helpers here ensures
consistency and avoids ad-hoc datetime formatting elsewhere.
"""

from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc  # alias for readability; equivalent to ``datetime.UTC`` on 3.11+


def now_rfc3339() -> str:
    """Current UTC time in RFC3339 with millisecond precision (``...sssZ``).

    Example output: ``2026-05-01T10:08:35.012Z``
    """
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def now_rfc3339_seconds() -> str:
    """Current UTC time in RFC3339 with second precision (no fractional).

    Example output: ``2026-05-01T10:08:35Z``
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_rfc3339(value: str) -> datetime:
    """Parse an RFC3339 string to a UTC-aware ``datetime``.

    Accepts both ``Z`` and ``+00:00`` suffix forms. Naive datetimes raise.
    """
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        msg = f"RFC3339 must be timezone-aware: {value!r}"
        raise ValueError(msg)
    return dt.astimezone(UTC)
