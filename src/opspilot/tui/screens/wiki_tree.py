"""Wiki Tree screen — list of wiki pages + ingest/query-to-page/promote (PR-21 / PR-26)."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, Input, Label, Static

_MODE_INGEST = "ingest"
_MODE_QTP = "qtp"


class WikiTreeScreen(Widget):
    DEFAULT_CSS = """
    WikiTreeScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    #wiki-input-row { height: 3; }
    WikiTreeScreen.input-hidden #wiki-input-row { display: none; }
    """

    BINDINGS = [
        Binding("p", "promote_page", "Promote", show=True),
        Binding("i", "start_ingest", "Ingest KB doc", show=True),
        Binding("q", "start_query_to_page", "Query→Page", show=True),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._selected_slug: str | None = None
        self._page_states: dict[str, str] = {}
        self._pending_mode = ""

    def compose(self) -> ComposeResult:
        yield Label("[b]Wiki Tree[/b] — [dim]P: promote  I: ingest  Q: query→page[/dim]")
        yield Static(id="wiki-input-row")
        yield DataTable(id="wiki-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.add_class("input-hidden")
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

    # ── input helpers ──────────────────────────────────────────────────────

    def _show_input(self, placeholder: str, mode: str) -> None:
        self._pending_mode = mode
        self.remove_class("input-hidden")
        bar = self.query_one("#wiki-input-row", Static)
        bar.remove_children()
        inp = Input(placeholder=placeholder, id="wiki-cmd-input")
        bar.mount(inp)
        inp.focus()

    def _hide_input(self) -> None:
        self._pending_mode = ""
        self.add_class("input-hidden")

    def action_start_ingest(self) -> None:
        self._show_input("KB doc ID to ingest (e.g. doc_abc12345)…", _MODE_INGEST)

    def action_start_query_to_page(self) -> None:
        self._show_input("Session ID (leave blank to scan all recent sessions)…", _MODE_QTP)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "wiki-cmd-input":
            return
        value = event.value.strip()
        mode = self._pending_mode
        self._hide_input()
        if mode == _MODE_INGEST:
            if value:
                self.do_wiki_ingest(value)
        elif mode == _MODE_QTP:
            self.do_query_to_page(value or None)

    def on_key(self, event: Any) -> None:
        if not self.has_class("input-hidden") and getattr(event, "key", "") == "escape":
            self._hide_input()

    # ── wiki ingest worker ─────────────────────────────────────────────────

    @work(thread=True)
    def do_wiki_ingest(self, doc_id: str) -> None:
        try:
            from ...config import load_config
            from ...memory.sqlite_store import SqliteStore
            from ...memory.storage_init import init_sqlite
            from ...providers.ollama import OllamaProvider
            from ...wiki.ingest import WikiIngestConfig
            from ...wiki.ingest import ingest as run_wiki_ingest

            cfg = load_config()
            kb_dir = cfg.home / "kb"
            sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
            provider = OllamaProvider(base_url=cfg.ollama_base_url)
            wiki_cfg = WikiIngestConfig(
                wiki_root=cfg.home / "wiki",
                namespace="opspilot:public-kb",
                owner="tui@opspilot",
                model="qwen2.5:7b",
            )
            result = run_wiki_ingest(doc_id, sqlite=sqlite, provider=provider, config=wiki_cfg)
            msg = f"✓ Wiki page created: {result.slug}"
            sev = "information"
        except Exception as exc:  # noqa: BLE001
            msg = f"Wiki ingest failed: {exc}"
            sev = "error"

        self.app.call_from_thread(self.notify, msg, severity=sev)
        if sev == "information":
            self.app.call_from_thread(self.refresh_pages)

    # ── query-to-page worker ───────────────────────────────────────────────

    @work(thread=True)
    def do_query_to_page(self, session_id: str | None) -> None:
        try:
            from ...config import load_config
            from ...providers.ollama import OllamaProvider
            from ...session import SessionManager
            from ...wiki.query_to_page import QueryToPageConfig, query_to_page, scan_and_convert

            cfg = load_config()
            provider = OllamaProvider(base_url=cfg.ollama_base_url)
            qtp_cfg = QueryToPageConfig(
                wiki_root=cfg.home / "wiki",
                namespace="opspilot:public-kb",
                owner="tui@opspilot",
                model="qwen2.5:7b",
            )
            session_mgr = SessionManager(home=cfg.home)
            if session_id:
                result = query_to_page(
                    session_id, session_manager=session_mgr, provider=provider, config=qtp_cfg
                )
                if result.skipped:
                    msg = f"Skipped: {result.skip_reason}"
                    sev = "warning"
                else:
                    msg = f"✓ Page created: {result.slug}"
                    sev = "information"
            else:
                results = scan_and_convert(
                    session_manager=session_mgr, provider=provider, config=qtp_cfg
                )
                created = sum(1 for r in results if not r.skipped)
                msg = f"✓ {created} page(s) created from {len(results)} session(s)"
                sev = "information"
        except Exception as exc:  # noqa: BLE001
            msg = f"Query→page failed: {exc}"
            sev = "error"

        self.app.call_from_thread(self.notify, msg, severity=sev)
        if sev == "information":
            self.app.call_from_thread(self.refresh_pages)

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
