"""Harness-specific error types."""

from __future__ import annotations

from ..errors import OpsPilotError


class HarnessError(OpsPilotError):
    """Base class for harness errors (fixture parse, evaluator failure, etc.)."""
