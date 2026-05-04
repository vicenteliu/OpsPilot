"""Lint Issues screen — wiki page lint (PR-21).

Full lint checker (slug collisions, broken [[links]], missing sections)
ships in a later PR.  For now this screen is a read-only viewer that will
be populated once the lint runner exists.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Rule


class LintIssuesScreen(Widget):
    DEFAULT_CSS = """
    LintIssuesScreen { height: 1fr; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Lint Issues[/b]")
        yield Rule()
        yield Label("No lint issues found.")
        yield Label("")
        yield Label(
            "[dim]Lint checker (broken [[links]], missing sections, slug collisions) "
            "ships in a future release.[/dim]"
        )
