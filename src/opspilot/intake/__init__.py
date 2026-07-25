"""Work-item intake — Source adapters and the intake loop (ADR-0013)."""

from .base import (
    IntakeLoop,
    IntakeReport,
    OpsPilotRunClient,
    SourceItem,
    SourceTransport,
    render_comment,
)
from .jsm import ReplayTransport, normalize_issue

__all__ = [
    "IntakeLoop",
    "IntakeReport",
    "OpsPilotRunClient",
    "ReplayTransport",
    "SourceItem",
    "SourceTransport",
    "normalize_issue",
    "render_comment",
]
