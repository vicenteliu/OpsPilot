"""Wiki query-to-page modal (PR-26).

Triggered from SessionsScreen (W key) — runs query_to_page for the
selected session and dismisses with the created slug (or None on cancel).
"""

from __future__ import annotations

import contextlib

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class WikiQueryModal(ModalScreen[str | None]):
    """Modal that converts a session into a wiki synthesis page."""

    DEFAULT_CSS = """
    WikiQueryModal {
        align: center middle;
    }
    WikiQueryModal > #dialog {
        width: 60;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    WikiQueryModal #status {
        margin-top: 1;
        color: $text-muted;
    }
    WikiQueryModal #buttons {
        margin-top: 1;
        layout: horizontal;
        height: auto;
        align: center middle;
    }
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self._session_id = session_id
        self._running = False

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical
        from textual.widgets import Static

        with Vertical(id="dialog"):
            yield Label("[b]Generate Wiki Page[/b]")
            yield Static(f"Session: {self._session_id}")
            yield Label("", id="status")
            with Static(id="buttons"):
                yield Button("Generate", id="generate", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "generate" and not self._running:
            self._running = True
            self.query_one("#generate", Button).disabled = True
            self._set_status("Running LLM synthesis…")
            self._run_worker()

    @work(thread=True)
    def _run_worker(self) -> None:
        try:
            from ..config import load_config
            from ..providers.ollama import OllamaProvider
            from ..session.manager import SessionManager
            from ..wiki.query_to_page import QueryToPageConfig
            from ..wiki.query_to_page import query_to_page as _q2p

            cfg = load_config()
            sm = SessionManager(home=cfg.home)
            provider = OllamaProvider()
            q2p_cfg = QueryToPageConfig(wiki_root=cfg.home / "wiki")
            result = _q2p(
                self._session_id,
                session_manager=sm,
                provider=provider,
                config=q2p_cfg,
            )
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._set_status, f"[red]Error:[/red] {exc}")
            return

        if result.skipped:
            self.app.call_from_thread(self._set_status, f"Skipped: {result.skip_reason[:80]}")
            self.app.call_from_thread(self._re_enable_generate)
        else:
            self.app.call_from_thread(self._set_status, f"[green]✓[/green] Created: {result.slug}")
            self.app.set_timer(1.5, lambda: self.dismiss(result.slug))

    def _set_status(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status", Label).update(msg)

    def _re_enable_generate(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#generate", Button).disabled = False
            self._running = False
