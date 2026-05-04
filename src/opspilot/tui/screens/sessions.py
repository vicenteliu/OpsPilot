"""Sessions screen — list of all sessions (PR-21 / PR-22 / PR-26)."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, Label


class SessionsScreen(Widget):
    DEFAULT_CSS = """
    SessionsScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [Binding("w", "wiki_from_session", "→ Wiki", show=True)]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._selected_session_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Label("[b]Sessions[/b]")
        yield DataTable(id="sessions-table", zebra_stripes=True)

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        dt.add_columns("ID", "Playbook", "Status", "Owner", "Created")
        self.load_sessions()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key
        if key is not None:
            self._selected_session_id = str(key.value)

    def refresh_sessions(self) -> None:
        """Clear and reload the sessions table (called after a new run completes)."""
        self._selected_session_id = None
        self.query_one(DataTable).clear()
        self.load_sessions()

    def action_wiki_from_session(self) -> None:
        """Open WikiQueryModal for the currently selected session (W key)."""
        if not self._selected_session_id:
            return
        from ..wiki_modal import WikiQueryModal

        self.app.push_screen(
            WikiQueryModal(self._selected_session_id),
            self._on_wiki_done,
        )

    def _on_wiki_done(self, slug: str | None) -> None:
        if slug:
            try:
                from .wiki_tree import WikiTreeScreen

                self.app.query_one(WikiTreeScreen).refresh_pages()
                self.app.action_switch_module("wiki-tree")  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    @work(thread=True)
    def load_sessions(self) -> None:
        from ...config import load_config
        from ...session import SessionManager

        cfg = load_config()
        sm = SessionManager(home=cfg.home)
        rows: list[tuple[str, str, str, str, str, str]] = []
        for sid in sm.list():
            try:
                s = sm.load(sid)
                rows.append(
                    (
                        sid,
                        s.id,
                        f"{s.playbook.id}@{s.playbook.version}",
                        s.status,
                        s.owner,
                        s.created_at[:19],
                    )
                )
            except Exception:  # noqa: BLE001
                rows.append((sid, sid, "—", "error", "—", "—"))

        def update() -> None:
            dt = self.query_one(DataTable)
            if rows:
                for key, *cells in rows:
                    dt.add_row(*cells, key=key)
            else:
                dt.add_row("(no sessions yet)", "", "", "", "")

        self.app.call_from_thread(update)
