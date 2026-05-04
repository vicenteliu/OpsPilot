"""Config screen — show resolved runtime config (PR-21)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label


class ConfigScreen(Widget):
    DEFAULT_CSS = """
    ConfigScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Config[/b]")
        yield DataTable(id="config-table", zebra_stripes=True)

    def on_mount(self) -> None:
        from ...config import load_config

        cfg = load_config()
        dt = self.query_one(DataTable)
        dt.add_columns("Field", "Value")
        dt.add_row("home", str(cfg.home))
        dt.add_row("ollama_base_url", cfg.ollama_base_url)
        dt.add_row("embed_model", cfg.embed_model)
        dt.add_row("log_level", cfg.log_level)
        dt.add_row("anthropic_api_key", "set" if cfg.anthropic_api_key else "(not set)")
        dt.add_row(
            "ui_modules",
            ", ".join(f"{k}={'on' if v else 'off'}" for k, v in cfg.ui_modules.items()),
        )
        dt.add_row(
            "playbooks_dir",
            str(cfg.playbooks_dir) if cfg.playbooks_dir else "(default)",
        )
