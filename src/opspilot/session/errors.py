"""Session-specific error types."""

from __future__ import annotations

from ..errors import OpsPilotError


class SessionError(OpsPilotError):
    """Base class for all session errors."""


class IllegalTransition(SessionError):  # noqa: N818  -- domain reads cleaner without -Error suffix
    """Raised when ``SessionManager.transition`` is called with a target
    state that's not reachable from the current state per
    ``session/SPEC.md §1``.
    """
