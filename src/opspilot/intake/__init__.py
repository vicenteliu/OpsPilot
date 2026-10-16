"""Work-item intake — Source adapters and the intake loop (ADR-0013)."""

from .base import (
    IntakeLoop,
    IntakeReport,
    IntakeState,
    Notifier,
    OpsPilotRunClient,
    SourceItem,
    SourceTransport,
    render_ask_comment,
    render_automated_comment,
    render_comment,
    with_reply,
)
from .jsm import JsmTransport, ReplayTransport, normalize_issue

__all__ = [
    "IntakeLoop",
    "IntakeReport",
    "IntakeState",
    "JsmTransport",
    "Notifier",
    "OpsPilotRunClient",
    "ReplayTransport",
    "SourceItem",
    "SourceTransport",
    "normalize_issue",
    "render_ask_comment",
    "render_automated_comment",
    "render_comment",
    "with_reply",
]
