"""Run modal — inline playbook execution from the TUI (PR-22).

User fills in playbook dir, ticket path, owner, then presses Run.
The orchestrator runs in a background worker thread; status updates
appear in the modal.  On success the modal dismisses itself after 1.5s
and returns the new session_id so the caller can refresh the Sessions
screen.  Cancel / error returns None.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class RunModal(ModalScreen[str | None]):
    """Modal dialog: pick a playbook + ticket and run the orchestrator."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    DEFAULT_CSS = """
    RunModal {
        align: center middle;
    }
    RunModal > #dialog {
        width: 68;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    RunModal .form-row {
        height: 3;
        layout: horizontal;
    }
    RunModal .form-lbl {
        width: 12;
        height: 3;
        content-align: left middle;
    }
    RunModal Input {
        width: 1fr;
    }
    RunModal #btn-row {
        height: 3;
        layout: horizontal;
        align: right middle;
        margin-top: 1;
    }
    RunModal #status-line {
        height: 1;
        margin-top: 1;
    }
    """

    def __init__(self, input_path: str = "", playbook_dir: str = "") -> None:
        super().__init__()
        self._init_input = input_path
        self._init_playbook = playbook_dir or "playbooks/pb_ticket_summary_zh"

    def compose(self) -> ComposeResult:
        with Static(id="dialog"):
            yield Label("[b]Run Playbook[/b]")
            with Static(classes="form-row"):
                yield Label("Playbook:", classes="form-lbl")
                yield Input(value=self._init_playbook, id="inp-playbook")
            with Static(classes="form-row"):
                yield Label("Ticket:", classes="form-lbl")
                yield Input(
                    value=self._init_input,
                    placeholder="path/to/ticket.json",
                    id="inp-ticket",
                )
            with Static(classes="form-row"):
                yield Label("Owner:", classes="form-lbl")
                yield Input(value="tui@opspilot", id="inp-owner")
            with Static(id="btn-row"):
                yield Button("Run", id="btn-run", variant="primary")
                yield Button("Cancel", id="btn-cancel")
            yield Label("Ready.", id="status-line")

    # ── UI event handlers ─────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-run":
            self._kick_run()

    # ── Run helpers ───────────────────────────────────────────────────

    def _kick_run(self) -> None:
        ticket = self.query_one("#inp-ticket", Input).value.strip()
        if not ticket:
            self._set_status("[red]Ticket path is required.[/red]")
            return
        playbook_dir = self.query_one("#inp-playbook", Input).value.strip()
        owner = self.query_one("#inp-owner", Input).value.strip() or "tui@opspilot"
        self.query_one("#btn-run", Button).disabled = True
        self._set_status("Starting…")
        self._run_worker(playbook_dir, ticket, owner)

    def _set_status(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status-line", Label).update(msg)

    @work(thread=True)
    def _run_worker(self, playbook_dir: str, ticket: str, owner: str) -> None:
        def st(msg: str) -> None:
            self.app.call_from_thread(self._set_status, msg)

        session_id: str | None = None
        try:
            from ..config import load_config
            from ..memory.lance_store import LanceStore
            from ..memory.sqlite_store import SqliteStore
            from ..memory.storage_init import init_sqlite
            from ..orchestrator import RunRequest, load_playbook, run_ticket_summary
            from ..providers import make_provider
            from ..redaction import Redactor
            from ..session import SessionManager

            st("Loading config…")
            cfg = load_config()

            pb_path = Path(playbook_dir)
            if not pb_path.is_absolute():
                pb_path = Path.cwd() / pb_path

            st("Loading playbook…")
            pb = load_playbook(pb_path)

            st("Opening KB stores…")
            kb_dir = cfg.home / "kb"
            kb_dir.mkdir(parents=True, exist_ok=True)
            sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
            lance = LanceStore.open_or_create(
                kb_dir / "lancedb",
                dim=768,
                embedding_model="ollama-local/nomic-embed-text-v2-moe@2026-04",
            )
            embed_provider = make_provider("ollama-local")
            primary_provider = make_provider(pb.model.provider_id, kind=pb.model.kind)

            def embed_fn(text: str) -> list[float]:
                return embed_provider.embed([text], model="nomic-embed-text-v2-moe")[0]

            st("Running playbook…")
            result = run_ticket_summary(
                RunRequest(playbook=pb, input_path=Path(ticket), owner=owner),
                session_manager=SessionManager(home=cfg.home),
                provider=primary_provider,
                redactor=Redactor.from_yaml(),
                embed_fn=embed_fn,
                sqlite_store=sqlite,
                lance_store=lance,
            )

            if result.error:
                st(f"[red]✗ {result.error}[/red]")
            else:
                session_id = result.session_id
                st(f"[green]✓ Done — {result.session_id[:24]}[/green]")

        except Exception as exc:  # noqa: BLE001
            st(f"[red]✗ {type(exc).__name__}: {exc}[/red]")

        finally:
            sid = session_id  # capture for closure

            def _finish() -> None:
                try:
                    self.query_one("#btn-run", Button).disabled = False
                    if sid:
                        self.set_timer(1.5, lambda: self.dismiss(sid))
                except Exception:  # noqa: BLE001
                    pass

            self.app.call_from_thread(_finish)
