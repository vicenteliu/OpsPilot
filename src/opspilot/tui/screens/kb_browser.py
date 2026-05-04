"""KB Browser screen — list of ingested KB documents (PR-21)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label


class KBBrowserScreen(Widget):
    DEFAULT_CSS = """
    KBBrowserScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]KB Browser[/b]")
        yield DataTable(id="kb-table", zebra_stripes=True)

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        dt.add_columns("Doc ID", "Title", "Lang", "Chunks", "Namespace", "Ingested")
        self.load_docs()

    @work(thread=True)
    def load_docs(self) -> None:
        from ...config import load_config

        cfg = load_config()
        db_path = cfg.home / "kb" / "sqlite.db"
        rows: list[tuple[str, ...]] = []

        if db_path.exists():
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT id, title, language, chunk_count, namespace, ingested_at "
                "FROM kb_documents ORDER BY ingested_at DESC"
            )
            for r in cur.fetchall():
                rows.append((
                    r["id"],
                    (r["title"] or "")[:40],
                    r["language"] or "—",
                    str(r["chunk_count"]),
                    r["namespace"] or "—",
                    (r["ingested_at"] or "")[:19],
                ))
            conn.close()

        def update() -> None:
            dt = self.query_one(DataTable)
            if rows:
                for row in rows:
                    dt.add_row(*row)
            else:
                dt.add_row("(no documents ingested yet)", "", "", "", "", "")

        self.app.call_from_thread(update)
