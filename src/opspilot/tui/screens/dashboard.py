"""Dashboard screen — summary stats panel (PR-21)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label, Rule, Static


class _StatCard(Static):
    DEFAULT_CSS = """
    _StatCard {
        border: round $primary;
        width: 1fr;
        height: auto;
        padding: 0 1;
        margin: 0 1;
    }
    """


class DashboardScreen(Widget):
    DEFAULT_CSS = """
    DashboardScreen { height: 1fr; padding: 1; }
    #dash-row { height: auto; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]OpsPilot Dashboard[/b]", id="dash-title")
        yield Rule()
        with Horizontal(id="dash-row"):
            yield _StatCard("Sessions\nloading…", id="stat-sessions")
            yield _StatCard("KB\nloading…", id="stat-kb")
            yield _StatCard("Wiki\nloading…", id="stat-wiki")
        yield Rule()
        yield _StatCard("Providers\n—", id="stat-providers")

    def on_mount(self) -> None:
        self.load_stats()

    @work(thread=True)
    def load_stats(self) -> None:
        from ...config import load_config
        from ...session import SessionManager

        cfg = load_config()

        # Sessions
        sm = SessionManager(home=cfg.home)
        sess_ids = sm.list()
        by_status: dict[str, int] = {}
        for sid in sess_ids:
            try:
                s = sm.load(sid)
                by_status[s.status] = by_status.get(s.status, 0) + 1
            except Exception:  # noqa: BLE001
                pass
        sess_lines = "\n".join(f"  {k}: {v}" for k, v in sorted(by_status.items()))
        sess_text = f"Sessions\ntotal: {len(sess_ids)}\n{sess_lines}" if sess_ids else "Sessions\n(none yet)"

        # KB
        db_path = cfg.home / "kb" / "sqlite.db"
        doc_count = chunk_count = 0
        if db_path.exists():
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            doc_count = conn.execute("SELECT COUNT(*) FROM kb_documents").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]
            conn.close()
        kb_text = f"KB\ndocs: {doc_count}\nchunks: {chunk_count}"

        # Wiki
        wiki_dir = cfg.home / "wiki" / "pages" / "summary"
        page_count = len(list(wiki_dir.glob("*.md"))) if wiki_dir.is_dir() else 0
        wiki_text = f"Wiki\npages: {page_count}"

        def update() -> None:
            try:
                self.query_one("#stat-sessions", _StatCard).update(sess_text)
                self.query_one("#stat-kb", _StatCard).update(kb_text)
                self.query_one("#stat-wiki", _StatCard).update(wiki_text)
            except Exception:  # noqa: BLE001 — widget may be detached on teardown
                pass

        self.app.call_from_thread(update)
