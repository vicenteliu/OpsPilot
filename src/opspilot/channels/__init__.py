"""Channel adapters — external messaging surfaces connected to OpsPilot.

A Channel fronts the KB-augmented chat in assist mode (see CONTEXT.md and
docs/adr/0012); Work-item intake through a Channel is a later phase.
"""

from .base import OpsPilotChatClient
from .telegram import TelegramChannel, TelegramConfig

__all__ = ["OpsPilotChatClient", "TelegramChannel", "TelegramConfig"]
