"""Orchestrator error hierarchy."""

from __future__ import annotations

from ..errors import OpsPilotError


class OrchestratorError(OpsPilotError):
    """Base class for orchestrator errors."""


class PlaybookError(OrchestratorError):
    """Raised when a playbook is missing required fields or files."""
