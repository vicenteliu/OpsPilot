"""OpsPilot TUI module (PR-20 / PR-22)."""

from .. import __version__  # single source of truth (derived from package metadata)
from .app import OpsPilotApp, run_tui
from .run_modal import RunModal

__all__ = ["OpsPilotApp", "RunModal", "__version__", "run_tui"]
