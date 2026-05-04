"""Wiki Tree screen — list of wiki pages (PR-21 / PR-26)."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, Label


class WikiTreeScreen(Widget):
    DEFAULT_CSS = """
    WikiTreeScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [Binding("p", "promote_page", "Promote", show=True)]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._selected_slug: str | None = None
        self._page_states: dict[str, str] = {}  # slug → lifecycle_state

    def compose(self) -> ComposeResult:
        yield Label("[b]Wiki Tree[/b]")
        yield DataTable(id="wiki-table", zebra_stripes=True)

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        dt.add_columns("Slug", "Title", "Kind", "State", "Lang", "Updated")
        self.load_pages()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key
        if key is not None:
            self._selected_slug = str(key.value)

    def refresh_pages(self) -> None:
        """Clear and reload the wiki pages table."""
        self._selected_slug = None
        self._page_states.clear()
        self.query_one(DataTable).clear()
        self.load_pages()

    def action_promote_page(self) -> None:
        """Promote the selected draft page to live (P key)."""
        if not self._selected_slug:
            return
        state = self._page_states.get(self._selected_slug, "")
        if state not in ("draft", "reviewed"):
            self.notify(
                f"'{self._selected_slug}' is '{state}' — only draft/reviewed can be promoted.",
                severity="warning",
            )
            return
        self._promote_worker(self._selected_slug)

    @work(thread=True)
    def _promote_worker(self, slug: str) -> None:
        try:
            from ...config import load_config
            from ...wiki.promote import PromoteConfig, promote_page

            cfg = load_config()
            result = promote_page(slug, PromoteConfig(wiki_root=cfg.home / "wiki"))
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self.notify, f"Promote failed: {exc}", severity="error")
            return

        if result.skipped:
            self.app.call_from_thread(self.notify, result.skip_reason, severity="warning")
        else:
            self.app.call_from_thread(
                self.notify,
                f"✓ {slug}: {result.old_state} → {result.new_state} (v{result.new_version})",
            )
            self.app.call_from_thread(self.refresh_pages)

    @work(thread=True)
    def load_pages(self) -> None:
        from ...config import load_config
        from ...wiki.page import read_page

        cfg = load_config()
        pages_root = cfg.home / "wiki" / "pages"
        rows: list[tuple[str, str, str, str, str, str, str]] = []
        page_states: dict[str, str] = {}

        if pages_root.is_dir():
            for md_file in sorted(pages_root.rglob("*.md")):
                try:
                    page = read_page(md_file)
                    rows.append(
                        (
                            page.slug,  # key
                            page.slug,
                            page.title[:40],
                            page.kind,
                            page.lifecycle_state,
                            page.language,
                            page.updated_at[:19],
                        )
                    )
                    page_states[page.slug] = page.lifecycle_state
                except Exception:  # noqa: BLE001
                    rows.append((md_file.stem, md_file.stem, "—", "—", "—", "—", "—"))

        def update() -> None:
            self._page_states = page_states
            dt = self.query_one(DataTable)
            if rows:
                for key, *cells in rows:
                    dt.add_row(*cells, key=key)
            else:
                dt.add_row("(no wiki pages yet)", "", "", "", "", "")

        self.app.call_from_thread(update)
