"""Providers screen — health status for configured providers (PR-21)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label

_PROVIDERS = [
    ("ollama-local", "ollama", "Ollama (local)"),
    ("anthropic", "anthropic", "Anthropic"),
    ("openai", "openai", "OpenAI"),
]


class ProvidersScreen(Widget):
    DEFAULT_CSS = """
    ProvidersScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Providers[/b]")
        yield DataTable(id="providers-table", zebra_stripes=True)

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        dt.add_columns("Provider", "Kind", "Status", "Detail")
        self.probe_providers()

    @work(thread=True)
    def probe_providers(self) -> None:
        from ...config import load_config
        from ...providers import make_provider

        cfg = load_config()
        rows: list[tuple[str, str, str, str]] = []

        for pid, kind, name in _PROVIDERS:
            detail = ""
            try:
                if kind == "anthropic" and not cfg.anthropic_api_key:
                    status = "○ no key"
                    detail = "set ANTHROPIC_API_KEY"
                elif kind == "openai":
                    status = "○ no key"
                    detail = "set OPENAI_API_KEY"
                else:
                    p = make_provider(pid)
                    ok = p.health_probe()
                    status = "● online" if ok else "○ offline"
            except Exception as exc:  # noqa: BLE001
                status = "○ error"
                detail = str(exc)[:60]
            rows.append((name, kind, status, detail))

        def update() -> None:
            dt = self.query_one(DataTable)
            dt.clear()
            for row in rows:
                dt.add_row(*row)

        self.app.call_from_thread(update)
