"""KB Browser screen — list + ingest + search (PR-21)."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, Input, Label, Static

_MODE_SEARCH = "search"
_MODE_INGEST = "ingest"
_MODE_CORRECT_ID = "correct_id"
_MODE_CORRECT_REASON = "correct_reason"
_MODE_CORRECT_CONTENT = "correct_content"


class KBBrowserScreen(Widget):
    DEFAULT_CSS = """
    KBBrowserScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    #kb-input-row { height: 3; }
    KBBrowserScreen.input-hidden #kb-input-row { display: none; }
    """

    BINDINGS = [
        Binding("i", "start_ingest", "Ingest file", show=True),
        Binding("s", "start_search", "Search KB", show=True),
        Binding("r", "reload_docs", "Reload", show=True),
        Binding("c", "show_conflicts", "Conflicts", show=True),
        Binding("e", "start_correct", "Correct chunk", show=True),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pending_mode = ""
        self._correct_chunk_id = ""
        self._correct_reason = ""

    def compose(self) -> ComposeResult:
        yield Label(
            "[b]KB Browser[/b] — [dim]I: ingest  S: search  R: reload  C: conflicts  E: correct chunk[/dim]"
        )
        yield Static(id="kb-input-row")
        yield DataTable(id="kb-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.add_class("input-hidden")
        dt = self.query_one(DataTable)
        dt.add_columns("Doc ID", "Title", "Lang", "Chunks", "Namespace", "Ingested")
        self.load_docs()

    # ── input bar helpers ──────────────────────────────────────────────────

    def _show_input(self, placeholder: str, mode: str) -> None:
        self._pending_mode = mode
        self.remove_class("input-hidden")
        bar = self.query_one("#kb-input-row", Static)
        bar.remove_children()
        inp = Input(placeholder=placeholder, id="kb-cmd-input")
        bar.mount(inp)
        inp.focus()

    def _hide_input(self) -> None:
        self._pending_mode = ""
        self.add_class("input-hidden")

    # ── bindings ───────────────────────────────────────────────────────────

    def action_start_ingest(self) -> None:
        self._show_input("Enter file path to ingest (Esc to cancel)…", _MODE_INGEST)

    def action_start_search(self) -> None:
        self._show_input("Enter search query (Esc to cancel)…", _MODE_SEARCH)

    def action_reload_docs(self) -> None:
        dt = self.query_one(DataTable)
        dt.clear()
        self.load_docs()

    def action_show_conflicts(self) -> None:
        self.show_conflicts()

    def action_start_correct(self) -> None:
        self._correct_chunk_id = ""
        self._correct_reason = ""
        self._show_input("Enter chunk ID to correct (e.g. chk_xxxxxxxx)…", _MODE_CORRECT_ID)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "kb-cmd-input":
            return
        value = event.value.strip()
        mode = self._pending_mode
        self._hide_input()
        if not value:
            return
        if mode == _MODE_INGEST:
            self.do_ingest(value)
        elif mode == _MODE_SEARCH:
            self.run_search(value)
        elif mode == _MODE_CORRECT_ID:
            self._correct_chunk_id = value
            self._show_input("Enter reason for correction…", _MODE_CORRECT_REASON)
        elif mode == _MODE_CORRECT_REASON:
            self._correct_reason = value
            self._show_input("Enter corrected content…", _MODE_CORRECT_CONTENT)
        elif mode == _MODE_CORRECT_CONTENT:
            self.do_correct(self._correct_chunk_id, self._correct_reason, value)

    def on_key(self, event: Any) -> None:
        if not self.has_class("input-hidden") and getattr(event, "key", "") == "escape":
            self._hide_input()

    # ── ingest worker ──────────────────────────────────────────────────────

    @work(thread=True)
    def do_ingest(self, path: str) -> None:
        from pathlib import Path as _Path

        from ...config import load_config
        from ...memory.ingestion import IngestConfig
        from ...memory.ingestion import ingest as run_ingest
        from ...memory.lance_store import LanceStore
        from ...memory.sqlite_store import SqliteStore
        from ...memory.storage_init import init_sqlite
        from ...providers import make_provider
        from ...redaction import Redactor

        cfg = load_config()
        kb_dir = cfg.home / "kb"
        kb_dir.mkdir(parents=True, exist_ok=True)
        sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
        lance = LanceStore.open_or_create(
            kb_dir / "lancedb", dim=768, embedding_model=cfg.embed_model
        )
        provider = make_provider("ollama-local", base_url=cfg.ollama_base_url)
        redactor = Redactor.from_yaml()

        def embed_fn(text: str) -> list[float]:
            return provider.embed([text], model=cfg.embed_model)[0]

        ic = IngestConfig(
            kb_id="opspilot:public-kb",
            namespace=None,
            classification="internal",
            embedding_model=f"ollama-local/{cfg.embed_model}@2026-04",
            embedding_dim=768,
        )
        try:
            stats = run_ingest(
                [_Path(path)],
                sqlite=sqlite,
                lance=lance,
                redactor=redactor,
                embed_fn=embed_fn,
                config=ic,
            )
            msg = f"✓ {stats.docs_succeeded} doc(s), {stats.chunks_total} chunk(s) ingested"
            sev = "information"
        except Exception as exc:  # noqa: BLE001
            msg = f"Ingest failed: {exc}"
            sev = "error"

        def refresh() -> None:
            self.notify(msg, severity=sev)
            dt = self.query_one(DataTable)
            dt.clear()
            self.load_docs()

        self.app.call_from_thread(refresh)

    # ── search worker ──────────────────────────────────────────────────────

    @work(thread=True)
    def run_search(self, query: str) -> None:
        from ...config import load_config
        from ...memory.lance_store import LanceStore
        from ...memory.retrieval import kb_search
        from ...memory.sqlite_store import SqliteStore
        from ...memory.storage_init import init_sqlite
        from ...providers import make_provider

        cfg = load_config()
        kb_dir = cfg.home / "kb"
        if not kb_dir.exists():
            self.app.call_from_thread(self.notify, "KB not initialised yet", severity="warning")
            return

        sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
        lance = LanceStore.open_or_create(
            kb_dir / "lancedb", dim=768, embedding_model=cfg.embed_model
        )
        provider = make_provider("ollama-local", base_url=cfg.ollama_base_url)

        def embed_fn(text: str) -> list[float]:
            return provider.embed([text], model=cfg.embed_model)[0]

        try:
            hits = kb_search(query, sqlite=sqlite, lance=lance, embed_fn=embed_fn, top_k=5)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self.notify, f"Search failed: {exc}", severity="error")
            return

        rows = [
            (
                h.chunk_id[:20],
                h.document_id[:20],
                "—",
                f"{h.score:.4f}",
                "—",
                (h.content or "").replace("\n", " ")[:60],
            )
            for h in hits
        ]

        def update() -> None:
            dt = self.query_one(DataTable)
            dt.clear()
            if rows:
                for row in rows:
                    dt.add_row(*row)
            else:
                dt.add_row("(no results)", "", "", "", "", "")

        self.app.call_from_thread(update)

    # ── load docs ──────────────────────────────────────────────────────────

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
                rows.append(
                    (
                        r["id"],
                        (r["title"] or "")[:40],
                        r["language"] or "—",
                        str(r["chunk_count"]),
                        r["namespace"] or "—",
                        (r["ingested_at"] or "")[:19],
                    )
                )
            conn.close()

        def update() -> None:
            dt = self.query_one(DataTable)
            if rows:
                for row in rows:
                    dt.add_row(*row)
            else:
                dt.add_row("(no documents ingested yet)", "", "", "", "", "")

        self.app.call_from_thread(update)

    # ── conflicts worker ────────────────────────────────────────────────────

    @work(thread=True)
    def show_conflicts(self) -> None:
        from ...config import load_config
        from ...memory.sqlite_store import SqliteStore
        from ...memory.storage_init import init_sqlite

        cfg = load_config()
        db_path = cfg.home / "kb" / "sqlite.db"
        if not db_path.exists():
            self.app.call_from_thread(self.notify, "KB not initialised yet", severity="warning")
            return

        sqlite = SqliteStore(init_sqlite(db_path))
        conflicts = sqlite.list_conflicts(status="open", limit=100)

        rows = [
            (
                r["id"],
                r.get("doc_a_title") or r["doc_a_id"],
                r.get("doc_b_title") or r["doc_b_id"],
                r["conflict_type"],
                f"{r['similarity']:.3f}",
                r["status"],
            )
            for r in conflicts
        ]

        def update() -> None:
            dt = self.query_one(DataTable)
            dt.clear()
            if rows:
                self.notify(f"{len(rows)} open conflict(s)", severity="warning")
                for row in rows:
                    dt.add_row(*row)
            else:
                self.notify("No open conflicts", severity="information")
                dt.add_row("(no open conflicts)", "", "", "", "", "")

        self.app.call_from_thread(update)

    # ── correct worker ─────────────────────────────────────────────────────

    @work(thread=True)
    def do_correct(self, chunk_id: str, reason: str, new_content: str) -> None:
        from ...config import load_config
        from ...memory.sqlite_store import SqliteStore
        from ...memory.storage_init import init_sqlite

        cfg = load_config()
        db_path = cfg.home / "kb" / "sqlite.db"
        if not db_path.exists():
            self.app.call_from_thread(self.notify, "KB not initialised yet", severity="warning")
            return

        sqlite = SqliteStore(init_sqlite(db_path))
        try:
            corr_id = sqlite.add_correction(
                chunk_id,
                corrected_by="tui-user",
                reason=reason,
                new_content=new_content,
            )
            self.app.call_from_thread(
                self.notify, f"Correction {corr_id} applied to {chunk_id}", severity="information"
            )
        except KeyError as exc:
            self.app.call_from_thread(self.notify, str(exc), severity="error")
