"""Providers screen — health status for configured providers (PR-21)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label

_PROVIDERS = [
    ("ollama-local", "ollama",     "Ollama (local)"),
    ("anthropic",   "anthropic",   "Anthropic"),
    ("openai",      "openai",      "OpenAI"),
    ("openrouter",  "openai",      "OpenRouter"),
    ("gemini",      "openai",      "Gemini"),
]

# Maps provider_id → env var name shown in the "no key" hint.
_KEY_ENV: dict[str, str] = {
    "anthropic":  "ANTHROPIC_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini":     "GEMINI_API_KEY",
}


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
        from ...errors import ProviderError
        from ...providers import make_provider

        rows: list[tuple[str, str, str, str]] = []

        for pid, kind, name in _PROVIDERS:
            status = ""
            detail = ""
            try:
                p = make_provider(pid, kind=kind)
                ok = p.health_probe()
                status = "● online" if ok else "○ offline"
            except ProviderError as exc:
                if exc.error_code == "missing_api_key":
                    status = "○ no key"
                    detail = f"set {_KEY_ENV.get(pid, 'API key')}"
                else:
                    status = "○ error"
                    detail = str(exc)[:60]
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
