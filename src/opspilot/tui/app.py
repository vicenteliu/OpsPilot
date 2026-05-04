"""OpsPilot TUI — main app shell (PR-20).

Layout:
  ┌─ Header ─────────────────────────────────────────┐
  │ NavSidebar (width=18) │ ContentSwitcher           │
  └─ Footer ─────────────────────────────────────────┘

Keys 1-8 jump directly to each module; Q quits.
PR-21 replaces each placeholder Label with full screen content.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import ContentSwitcher, Footer, Header, Label, ListItem, ListView, Static

from .screens import (
    ConfigScreen,
    DashboardScreen,
    HarnessScreen,
    KBBrowserScreen,
    LintIssuesScreen,
    ProvidersScreen,
    SessionsScreen,
    WikiTreeScreen,
)

# (key, screen_id, label) — order defines sidebar order and key 1-8 mapping
_NAV: list[tuple[str, str, str]] = [
    ("1", "dashboard", "Dashboard"),
    ("2", "sessions", "Sessions"),
    ("3", "kb-browser", "KB Browser"),
    ("4", "wiki-tree", "Wiki Tree"),
    ("5", "harness", "Harness"),
    ("6", "lint-issues", "Lint Issues"),
    ("7", "providers", "Providers"),
    ("8", "config", "Config"),
]

_SCREEN_MAP: dict[str, type] = {
    "dashboard": DashboardScreen,
    "sessions": SessionsScreen,
    "kb-browser": KBBrowserScreen,
    "wiki-tree": WikiTreeScreen,
    "harness": HarnessScreen,
    "lint-issues": LintIssuesScreen,
    "providers": ProvidersScreen,
    "config": ConfigScreen,
}


class OpsPilotApp(App[None]):
    """OpsPilot terminal workbench."""

    TITLE = "OpsPilot"
    CSS = """
    #sidebar {
        width: 18;
        height: 100%;
        dock: left;
        background: $panel;
        border-right: solid $primary-darken-2;
    }

    #sidebar ListView {
        height: 1fr;
        background: $panel;
    }

    #sidebar ListItem {
        padding: 0 1;
    }

    #content-area {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("1", "switch_module('dashboard')", "Dashboard", show=False),
        Binding("2", "switch_module('sessions')", "Sessions", show=False),
        Binding("3", "switch_module('kb-browser')", "KB Browser", show=False),
        Binding("4", "switch_module('wiki-tree')", "Wiki Tree", show=False),
        Binding("5", "switch_module('harness')", "Harness", show=False),
        Binding("6", "switch_module('lint-issues')", "Lint Issues", show=False),
        Binding("7", "switch_module('providers')", "Providers", show=False),
        Binding("8", "switch_module('config')", "Config", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Static(id="sidebar"):
                yield ListView(
                    *[
                        ListItem(Label(f"[{key}] {label}"), id=f"nav-{screen_id}")
                        for key, screen_id, label in _NAV
                    ]
                )
            with ContentSwitcher(initial="dashboard", id="content-area"):
                for _, screen_id, _ in _NAV:
                    screen_cls = _SCREEN_MAP[screen_id]
                    yield screen_cls(id=screen_id)
        yield Footer()

    def action_switch_module(self, screen_id: str) -> None:
        self.query_one(ContentSwitcher).current = screen_id
        # Sync sidebar highlight to active module
        for _, sid, _ in _NAV:
            item = self.query_one(f"#nav-{sid}", ListItem)
            item.highlighted = sid == screen_id

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id and event.item.id.startswith("nav-"):
            screen_id = event.item.id[4:]
            self.action_switch_module(screen_id)

    @property
    def active_module(self) -> str:
        return self.query_one(ContentSwitcher).current or "dashboard"


def run_tui() -> None:
    """Launch the OpsPilot TUI (entry point for `opspilot tui`)."""
    OpsPilotApp().run()
