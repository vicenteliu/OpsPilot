"""Iteration screen — skill lineage history and variant verdicts (PR-28)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label


class IterationScreen(Widget):
    DEFAULT_CSS = """
    IterationScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Iteration History — Skill Lineage[/b]")
        yield DataTable(id="iteration-table", zebra_stripes=True)

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        dt.add_columns("Skill", "Version", "Parent", "Promoted", "Iteration", "Summary")
        self.load_lineage()

    @work(thread=True)
    def load_lineage(self) -> None:
        from ...config import load_config

        cfg = load_config()
        lineage_dir = cfg.home / "skills" / "lineage"

        rows: list[tuple[str, ...]] = []
        if lineage_dir.exists():
            rows = _read_lineage_rows(lineage_dir)

        def update() -> None:
            try:
                dt = self.query_one(DataTable)
                if rows:
                    for row in rows:
                        dt.add_row(*row)
                else:
                    dt.add_row("(no lineage files yet)", "", "", "", "", "")
            except Exception:  # noqa: BLE001
                pass

        self.app.call_from_thread(update)


def _read_lineage_rows(lineage_dir) -> list[tuple[str, ...]]:
    import yaml
    from pathlib import Path

    rows = []
    for yaml_file in sorted(Path(lineage_dir).glob("*.yaml")):
        skill_name = yaml_file.stem
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        for v in reversed(data.get("versions", [])):
            itr = v.get("iteration") or "—"
            if itr != "—" and len(itr) > 18:
                itr = itr[:16] + "…"
            summary = v.get("summary", "")[:70]
            rb = " ⟲" if v.get("rolled_back") else ""
            rows.append(
                (
                    skill_name,
                    f"v{v.get('version', '?')}{rb}",
                    v.get("parent") or "—",
                    v.get("promoted_at", "")[:10],
                    itr,
                    summary,
                )
            )
    return rows
