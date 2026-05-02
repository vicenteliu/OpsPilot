"""Pretty-print harness results."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .types import EvalResult


def render_result_table(result: EvalResult, *, console: Console | None = None) -> None:
    """Print a per-evaluator table + weighted summary row."""
    console = console or Console()
    table = Table(title=f"Harness · {result.fixture_id} ({result.playbook_ref})")
    table.add_column("Evaluator")
    table.add_column("Type", overflow="fold")
    table.add_column("Score", justify="right")
    table.add_column("Pass")
    table.add_column("Details", overflow="fold")

    for er in result.evaluators:
        status = "[green]PASS[/green]" if er.passed else "[red]FAIL[/red]"
        details_short = _short_details(er.details)
        table.add_row(
            er.id,
            er.type,
            f"{er.score:.3f}",
            status,
            details_short,
        )

    weighted = result.weighted_score
    overall = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
    table.add_row(
        "[bold]weighted_score[/bold]",
        "",
        f"[bold]{weighted:.3f}[/bold]",
        overall,
        f"flags: {result.flags or '-'}",
    )
    console.print(table)
    console.print(
        f"\nrun_id={result.run_id}  session={result.output.get('session_id', '-')}  "
        f"latency={result.latency_ms.get('total', '?')}ms"
    )


def _short_details(d: dict[str, object]) -> str:
    """Produce a 1-line preview of an evaluator's details payload."""
    if not d:
        return ""
    if "missing" in d and d["missing"]:
        return f"missing={d['missing']}"
    if "leaked" in d and d["leaked"]:
        return f"leaked={d['leaked']}"
    if "error" in d:
        return f"error={str(d['error'])[:60]}"
    if "invalid" in d and d["invalid"]:
        return f"invalid={d['invalid']}"
    if "expected" in d and "retrieved" in d:
        return f"expected={d['expected']} retrieved={d['retrieved']}"
    # Fallback to first key/value.
    k, v = next(iter(d.items()))
    return f"{k}={str(v)[:60]}"
