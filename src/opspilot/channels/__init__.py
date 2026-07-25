"""Channel adapters — external messaging surfaces connected to OpsPilot.

A Channel fronts the KB-augmented chat in assist mode (ADR-0012), files
Work items via intake commands (ADR-0014), or receives push-only
notifications in notify mode (ADR-0016). See CONTEXT.md.
"""

from .base import OpsPilotChatClient
from .telegram import TelegramChannel, TelegramConfig
from .wecom import WeComNotifier

__all__ = ["OpsPilotChatClient", "TelegramChannel", "TelegramConfig", "WeComNotifier"]
