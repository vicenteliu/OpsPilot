"""Sessions screen — list of all sessions (PR-21)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label


class SessionsScreen(Widget):
    DEFAULT_CSS = """
    SessionsScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Sessions[/b]")
        yield DataTable(id="sessions-table", zebra_stripes=True)

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        dt.add_columns("ID", "Playbook", "Status", "Owner", "Created")
        self.load_sessions()

    @work(thread=True)
    def load_sessions(self) -> None:
        from ...config import load_config
        from ...session import SessionManager

        cfg = load_config()
        sm = SessionManager(home=cfg.home)
        rows: list[tuple[str, ...]] = []
        for sid in sm.list():
            try:
                s = sm.load(sid)
                rows.append((
                    s.id,
                    f"{s.playbook.id}@{s.playbook.version}",
                    s.status,
                    s.owner,
                    s.created_at[:19],
                ))
            except Exception:  # noqa: BLE001
                rows.append((sid, "—", "error", "—", "—"))

        def update() -> None:
            dt = self.query_one(DataTable)
            if rows:
                for row in rows:
                    dt.add_row(*row)
            else:
                dt.add_row("(no sessions yet)", "", "", "", "")

        self.app.call_from_thread(update)
