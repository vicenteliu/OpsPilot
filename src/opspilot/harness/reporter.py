"""Pretty-print harness results."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .types import EvalResult


def run_failure(result: EvalResult) -> str | None:
    """The reason this run never produced an artifact, or ``None`` if it did.

    A run the provider refused still scores: the evaluators that do not read the
    artifact (``must_not_contain``, ``rag_recall_at_k``) pass against nothing, so
    an empty artifact lands around 0.27 rather than 0. Printed as a number next
    to real results, an HTTP 400 and an upstream 429 are indistinguishable from a
    model that answered badly — which is the one thing a model-comparison table
    must not blur (#171).

    The discriminator is **output tokens**: an error with none means the model
    never answered. An error *with* output — unparseable JSON, a loop that ran
    out of turns — is a genuine quality signal and keeps its score.
    """
    orchestrator = result.extensions.get("orchestrator") or {}
    if not isinstance(orchestrator, dict):
        return None
    error = orchestrator.get("error")
    if not error or orchestrator.get("output_tokens"):
        return None
    return str(error)


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

    failure = run_failure(result)
    if failure is None:
        table.add_row(
            "[bold]weighted_score[/bold]",
            "",
            f"[bold]{result.weighted_score:.3f}[/bold]",
            "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]",
            f"flags: {result.flags or '-'}",
        )
    else:
        # No score row: the run never reached an artifact, so there is nothing
        # here to compare against another model.
        table.add_row(
            "[bold]run[/bold]",
            "",
            "[bold]—[/bold]",
            "[red]DID NOT RUN[/red]",
            failure,
        )
    console.print(table)
    if failure is not None:
        console.print(f"\n[red]run failed:[/red] {failure}")
        console.print("[dim]no score — this run produced no artifact to evaluate.[/dim]")
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
