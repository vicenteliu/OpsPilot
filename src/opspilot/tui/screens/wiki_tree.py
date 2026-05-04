"""Wiki Tree screen — list of wiki pages (PR-21)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label


class WikiTreeScreen(Widget):
    DEFAULT_CSS = """
    WikiTreeScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Wiki Tree[/b]")
        yield DataTable(id="wiki-table", zebra_stripes=True)

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        dt.add_columns("Slug", "Title", "Kind", "State", "Lang", "Updated")
        self.load_pages()

    @work(thread=True)
    def load_pages(self) -> None:
        from ...config import load_config
        from ...wiki.page import read_page

        cfg = load_config()
        pages_root = cfg.home / "wiki" / "pages"
        rows: list[tuple[str, ...]] = []

        if pages_root.is_dir():
            for md_file in sorted(pages_root.rglob("*.md")):
                try:
                    page = read_page(md_file)
                    rows.append((
                        page.slug,
                        page.title[:40],
                        page.kind,
                        page.lifecycle_state,
                        page.language,
                        page.updated_at[:19],
                    ))
                except Exception:  # noqa: BLE001
                    rows.append((md_file.stem, "—", "—", "—", "—", "—"))

        def update() -> None:
            dt = self.query_one(DataTable)
            if rows:
                for row in rows:
                    dt.add_row(*row)
            else:
                dt.add_row("(no wiki pages yet)", "", "", "", "", "")

        self.app.call_from_thread(update)
