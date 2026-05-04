"""Lint Issues screen placeholder (PR-20).  Full content in PR-21."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label


class LintIssuesScreen(Screen):
    """Lint Issues module — placeholder, content added in PR-21."""

    def compose(self) -> ComposeResult:
        yield Label("Lint Issues  (PR-21 will fill this in)", id="lint_issues-placeholder")
