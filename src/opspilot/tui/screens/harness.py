"""Harness screen — recent eval results (PR-21)."""

from __future__ import annotations

import json

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label


class HarnessScreen(Widget):
    DEFAULT_CSS = """
    HarnessScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Harness — Eval Results[/b]")
        yield DataTable(id="harness-table", zebra_stripes=True)

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        dt.add_columns("Fixture", "Playbook", "Score", "Pass", "Run at")
        self.load_results()

    @work(thread=True)
    def load_results(self) -> None:
        from ...config import load_config

        cfg = load_config()
        rows: list[tuple[str, ...]] = []

        # Scan ~/.opspilot/ for any results.jsonl files
        for results_file in sorted(cfg.home.rglob("results.jsonl")):
            try:
                with results_file.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        d = json.loads(line)
                        rows.append((
                            d.get("fixture_id", "—"),
                            d.get("playbook_id", "—"),
                            f"{d.get('weighted_score', 0):.3f}",
                            "✓" if d.get("pass") else "✗",
                            (d.get("run_at") or "")[:19],
                        ))
            except Exception:  # noqa: BLE001
                pass

        def update() -> None:
            dt = self.query_one(DataTable)
            if rows:
                for row in rows:
                    dt.add_row(*row)
            else:
                dt.add_row("(no harness results found)", "", "", "", "")

        self.app.call_from_thread(update)
