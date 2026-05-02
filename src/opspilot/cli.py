"""OpsPilot CLI entry point.

Stage 1 PR-1 implements:

* ``opspilot init``       — create ``~/.opspilot/`` subtree
* ``opspilot validate``   — JSON-schema-validate one file or a directory
* ``opspilot schemas``    — list registered schemas (debug)

Subsequent PRs add ``ingest``, ``run``, ``harness``, ``inspect``.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import ensure_home, load_config
from .errors import OpsPilotError, SchemaError
from .schemas import (
    infer_schema_name,
    iter_items,
    load_data,
    registry,
)
from .schemas import (
    validate as schema_validate,
)

app = typer.Typer(
    name="opspilot",
    help="AI-augmented IT ops workbench (Stage 1: Python core + CLI).",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

_console = Console()
_err = Console(stderr=True, style="red")


def _version_callback(value: bool) -> None:
    if value:
        _console.print(f"opspilot {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(  # noqa: ARG001
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """OpsPilot — AI-augmented IT ops workbench."""


# ──────────────────────────────────────────────────────────────────────────
#  init
# ──────────────────────────────────────────────────────────────────────────


@app.command()
def init(
    home: Path | None = typer.Option(
        None,
        "--home",
        help="Override OPSPILOT_HOME. Default: ~/.opspilot",
    ),
) -> None:
    """Initialize the OpsPilot home directory."""
    cfg = load_config()
    target = home.expanduser() if home else cfg.home
    created = ensure_home(target)
    _console.print(f"[green]OK[/green] Initialized OpsPilot home at {target}")
    for p in created:
        _console.print(f"  - {p}")


# ──────────────────────────────────────────────────────────────────────────
#  validate
# ──────────────────────────────────────────────────────────────────────────


def _list_target_files(path: Path, *, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if recursive:
        return sorted(p for p in path.rglob("*") if p.is_file())
    return sorted(p for p in path.iterdir() if p.is_file())


@app.command()
def validate(
    path: Path = typer.Argument(..., exists=True, help="File or directory to validate."),
    schema: str | None = typer.Option(
        None,
        "--schema",
        "-s",
        help="Force a schema name (e.g. 'session'); else auto-infer per file.",
    ),
    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        help="Recurse into subdirectories (default on).",
    ),
) -> None:
    """Validate file(s) against their inferred (or explicit) JSON schemas."""
    targets = _list_target_files(path, recursive=recursive)

    table = Table(title="Validation results", show_lines=False)
    table.add_column("File", overflow="fold")
    table.add_column("Schema")
    table.add_column("Status", justify="right")

    failures: list[tuple[Path, str]] = []
    skipped = 0
    passed = 0

    for f in targets:
        schema_name = schema or infer_schema_name(f)
        if schema_name is None:
            skipped += 1
            continue
        if f.suffix.lower() not in (".json", ".jsonl", ".yaml", ".yml"):
            skipped += 1
            continue

        rel = str(f.relative_to(path) if path.is_dir() else f)
        try:
            data = load_data(f)
            for item in iter_items(data):
                schema_validate(schema_name, item)
            table.add_row(rel, schema_name, "[green]PASS[/green]")
            passed += 1
        except SchemaError as e:
            short = str(e)[:80]
            table.add_row(rel, schema_name, f"[red]FAIL[/red] {short}")
            failures.append((f, str(e)))
        except Exception as e:  # noqa: BLE001 — surface any loader/parser error too
            short = f"{type(e).__name__}: {e}"[:80]
            table.add_row(rel, schema_name, f"[red]ERROR[/red] {short}")
            failures.append((f, str(e)))

    if passed or failures:
        _console.print(table)
    _console.print()
    _console.print(
        f"Total: {passed} passed · {len(failures)} failed · "
        f"{skipped} skipped (no schema inferred)"
    )

    if failures:
        _err.print(f"\n[red]VALIDATION FAILED[/red] ({len(failures)} files)")
        raise typer.Exit(code=2)


# ──────────────────────────────────────────────────────────────────────────
#  schemas (debug helper)
# ──────────────────────────────────────────────────────────────────────────


@app.command(name="schemas")
def list_schemas() -> None:
    """List all registered schemas (debug)."""
    reg = registry()
    table = Table(title=f"{len(reg)} schemas registered")
    table.add_column("Name")
    table.add_column("$id", overflow="fold")
    table.add_column("Title")
    for name, schema in sorted(reg.items()):
        table.add_row(name, schema.get("$id", ""), schema.get("title", ""))
    _console.print(table)


# ──────────────────────────────────────────────────────────────────────────
#  Module entrypoint
# ──────────────────────────────────────────────────────────────────────────


def main() -> int:
    """Entry-point used by `python -m opspilot` (handles top-level exceptions)."""
    try:
        app()
    except OpsPilotError as e:
        _err.print(f"[red]Error:[/red] {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
