"""OpsPilot TUI — main app shell (PR-20 / PR-22 / PR-28).

Layout:
  ┌─ Header ─────────────────────────────────────────┐
  │ NavSidebar (width=18) │ ContentSwitcher           │
  └─ Footer ─────────────────────────────────────────┘

Keys 1-9 jump directly to each module; R opens the Run modal; Q quits.
PR-28 adds key 9 → Iteration screen.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import ContentSwitcher, Footer, Header, Label, ListItem, ListView, Static

from .run_modal import RunModal
from .screens import (
    ConfigScreen,
    DashboardScreen,
    HarnessScreen,
    IterationScreen,
    KBBrowserScreen,
    LintIssuesScreen,
    ProvidersScreen,
    SessionsScreen,
    WikiTreeScreen,
)

# (key, screen_id, label) — order defines sidebar order and key 1-9 mapping
_NAV: list[tuple[str, str, str]] = [
    ("1", "dashboard", "Dashboard"),
    ("2", "sessions", "Sessions"),
    ("3", "kb-browser", "KB Browser"),
    ("4", "wiki-tree", "Wiki Tree"),
    ("5", "harness", "Harness"),
    ("6", "lint-issues", "Lint Issues"),
    ("7", "providers", "Providers"),
    ("8", "config", "Config"),
    ("9", "iteration", "Iteration"),
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
    "iteration": IterationScreen,
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
        Binding("9", "switch_module('iteration')", "Iteration", show=False),
        Binding("r", "start_run", "Run", show=True),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, run_input: str = "", run_playbook: str = "") -> None:
        super().__init__()
        self._run_input = run_input
        self._run_playbook = run_playbook

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

    def on_mount(self) -> None:
        if self._run_input:
            self.set_timer(0.3, self._auto_open_run_modal)

    def _auto_open_run_modal(self) -> None:
        self.push_screen(
            RunModal(input_path=self._run_input, playbook_dir=self._run_playbook),
            self._on_run_done,
        )

    def action_switch_module(self, screen_id: str) -> None:
        self.query_one(ContentSwitcher).current = screen_id
        # Sync sidebar highlight to active module
        for _, sid, _ in _NAV:
            item = self.query_one(f"#nav-{sid}", ListItem)
            item.highlighted = sid == screen_id

    def action_start_run(self) -> None:
        """Open the Run modal (bound to `r`)."""
        self.push_screen(RunModal(), self._on_run_done)

    def _on_run_done(self, session_id: str | None) -> None:
        """Called when RunModal dismisses; refresh Sessions if a run completed."""
        if session_id:
            try:
                self.query_one(SessionsScreen).refresh_sessions()
                self.action_switch_module("sessions")
            except Exception:  # noqa: BLE001
                pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id and event.item.id.startswith("nav-"):
            screen_id = event.item.id[4:]
            self.action_switch_module(screen_id)

    @property
    def active_module(self) -> str:
        return self.query_one(ContentSwitcher).current or "dashboard"


def run_tui(*, run_input: str = "", run_playbook: str = "") -> None:
    """Launch the OpsPilot TUI.

    If ``run_input`` is set the Run modal opens automatically on startup.
    """
    OpsPilotApp(run_input=run_input, run_playbook=run_playbook).run()
