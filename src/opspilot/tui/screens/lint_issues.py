"""Lint Issues screen — wiki page lint results (PR-23)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label

_SEVERITY_STYLE = {
    "critical": "[bold red]critical[/bold red]",
    "high": "[red]high[/red]",
    "medium": "[yellow]medium[/yellow]",
    "low": "[dim]low[/dim]",
}


class LintIssuesScreen(Widget):
    DEFAULT_CSS = """
    LintIssuesScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[b]Lint Issues[/b]")
        yield DataTable(id="lint-table", zebra_stripes=True)

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        dt.add_columns("Type", "Sev", "Page", "Summary")
        self.load_lint()

    @work(thread=True)
    def load_lint(self) -> None:
        from ...config import load_config
        from ...wiki.lint import lint_wiki

        try:
            cfg = load_config()
            wiki_root = cfg.home / "wiki"
            issues = lint_wiki(wiki_root)
        except Exception:  # noqa: BLE001
            issues = []

        rows: list[tuple[str, ...]] = []
        for issue in issues:
            sev = _SEVERITY_STYLE.get(issue.severity, issue.severity)
            rows.append(
                (
                    issue.issue_type,
                    sev,
                    issue.page_slug or "—",
                    issue.summary[:80],
                )
            )

        def update() -> None:
            try:
                dt = self.query_one(DataTable)
                if rows:
                    for row in rows:
                        dt.add_row(*row)
                else:
                    dt.add_row("No lint issues found.", "", "", "")
            except Exception:  # noqa: BLE001
                pass

        self.app.call_from_thread(update)
