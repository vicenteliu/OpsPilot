"""OpsPilot CLI entry point.

* ``opspilot init``         — create ``~/.opspilot/`` subtree
* ``opspilot validate``     — JSON-schema-validate one file or a directory
* ``opspilot schemas``      — list registered schemas (debug)
* ``opspilot ingest``       — run KB ingestion pipeline (PR-5)
* ``opspilot kb-search``    — hybrid retrieval over KB (PR-5)
* ``opspilot run``          — run a playbook end-to-end (PR-7)
* ``opspilot harness run``  — run a single fixture through harness (PR-8)
* ``opspilot harness golden`` — run the Stage 1 golden test (PR-8)
* ``opspilot wiki ingest``            — generate wiki page from KB document (PR-19)
* ``opspilot tui``                    — launch the terminal UI (PR-20)
* ``opspilot iteration sense``        — aggregate feedback weight (PR-27)
* ``opspilot iteration evaluate``     — apply promotion gates to variant eval results (PR-27)
* ``opspilot iteration promote``      — promote variant + update lineage (PR-27)
* ``opspilot iteration validate``     — validate iteration directory invariants (PR-27)
* ``opspilot sandbox dry-run``        — preview action without executing (PR-30)
* ``opspilot sandbox run``            — execute action in Docker L2 hardened container (PR-30)
* ``opspilot mcp list``               — list MCP servers and their tools (PR-31)
* ``opspilot mcp probe <id>``         — health-check a single MCP server (PR-31)
* ``opspilot serve``                  — start the FastAPI server (PR-32)
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from .config import Config
    from .sandbox.types import ActionRequest

from . import __version__
from .config import ensure_home, load_config
from .errors import OpsPilotError, SchemaError
from .harness import load_fixture, load_golden, run_harness
from .harness.reporter import render_result_table
from .iteration.engine import IterationEngine
from .iteration.types import IterationPolicy
from .kb.conflict import resolve_conflict
from .kb.ingestion import SOURCE_AUTHORITIES, IngestConfig, SourceAuthority
from .kb.ingestion import ingest as run_ingest
from .kb.kb_loader import load_kb_fixture
from .kb.lance_store import LanceStore
from .kb.retrieval import kb_search
from .kb.sqlite_store import SqliteStore
from .kb.storage_init import init_sqlite
from .orchestrator import RunRequest, load_playbook, run_ticket_summary
from .orchestrator.ticket_summary import _format_doc_request
from .providers import make_provider
from .redaction import Redactor
from .schemas import (
    infer_schema_name,
    iter_items,
    load_data,
    registry,
)
from .schemas import (
    validate as schema_validate,
)
from .session import SessionManager
from .session.types import Model
from .wiki.ingest import WikiIngestConfig
from .wiki.ingest import ingest as run_wiki_ingest

REPO_ROOT = Path(__file__).resolve().parents[2]

app = typer.Typer(
    name="opspilot",
    help="AI-augmented IT ops workbench (Stage 1: Python core + CLI).",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

_console = Console()
_err = Console(stderr=True, style="red")


def _cli_actor() -> str:
    """Attribution for records written outside an HTTP request.

    There is no auth context on the CLI, so the OS user is the best available
    answer. It is advisory, not evidence: anyone who can run this can also edit
    the SQLite file directly. Over HTTP the actor comes from the caller's
    Identity instead.
    """
    import getpass

    return f"cli:{getpass.getuser()}"


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
    home: Path | None = typer.Option(  # noqa: B008
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
    path: Path = typer.Argument(..., exists=True, help="File or directory to validate."),  # noqa: B008
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
        f"Total: {passed} passed · {len(failures)} failed · {skipped} skipped (no schema inferred)"
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
#  ingest (PR-5)
# ──────────────────────────────────────────────────────────────────────────


def _open_kb_stores(
    *, home: Path, embedding_dim: int, embedding_model: str
) -> tuple[SqliteStore, LanceStore]:
    """Open the SQLite + LanceDB stores under ``<home>/kb/``."""
    kb_dir = home / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
    lance = LanceStore.open_or_create(
        kb_dir / "lancedb",
        dim=embedding_dim,
        embedding_model=embedding_model,
    )
    return sqlite, lance


@app.command()
def ingest(
    paths: list[Path] = typer.Argument(  # noqa: B008
        ..., exists=True, help="One or more files / dirs to ingest."
    ),
    kb_id: str = typer.Option(
        "opspilot:public-kb",
        "--kb-id",
        help="KB namespace identifier (also used as namespace if --namespace omitted).",
    ),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        help="Override namespace (default: same as --kb-id).",
    ),
    classification: str = typer.Option(
        "internal",
        "--classification",
        help="public | internal | confidential | restricted (restricted skips vector path).",
    ),
    source_authority: str = typer.Option(
        "internal",
        "--source-authority",
        help="official | vendor | internal | unverified — how much this source is trusted.",
    ),
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04",
        "--embedding-model",
        help="Provider/model@date pinned reference.",
    ),
    embedding_dim: int = typer.Option(
        768, "--embedding-dim", help="Vector dim; must match the embedding model."
    ),
    embed_model_short: str = typer.Option(
        "nomic-embed-text-v2-moe",
        "--ollama-embed-model",
        help="Short Ollama tag (without provider prefix) used at the wire.",
    ),
) -> None:
    """Ingest one or more files into the KB."""
    if source_authority not in SOURCE_AUTHORITIES:
        # The column has a CHECK constraint; catching it here beats a sqlite
        # error raised part-way through a batch.
        _err.print(
            f"[red]--source-authority must be one of "
            f"{' | '.join(SOURCE_AUTHORITIES)}; got {source_authority!r}[/red]"
        )
        raise typer.Exit(code=1)

    cfg = load_config()
    sqlite, lance = _open_kb_stores(
        home=cfg.home,
        embedding_dim=embedding_dim,
        embedding_model=embedding_model,
    )
    redactor = Redactor.from_yaml()
    provider = make_provider("ollama-local")

    def embed_fn(text: str) -> list[float]:
        return provider.embed([text], model=embed_model_short)[0]

    ic = IngestConfig(
        kb_id=kb_id,
        namespace=namespace,
        classification=classification,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        source_authority=cast("SourceAuthority", source_authority),
    )
    stats = run_ingest(
        paths,
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=embed_fn,
        config=ic,
    )

    table = Table(title=f"Ingest run {stats.run_id}")
    table.add_column("File", overflow="fold")
    table.add_column("Doc ID")
    table.add_column("Chunks", justify="right")
    table.add_column("Status", justify="right")

    for fr in stats.files:
        if fr.error:
            status = f"[red]ERROR[/red] {fr.error[:60]}"
        elif fr.chunks_skipped_unchanged:
            status = "[yellow]unchanged[/yellow]"
        else:
            status = "[green]ingested[/green]"
        table.add_row(
            str(fr.source_path),
            fr.document_id or "-",
            str(fr.chunks_written),
            status,
        )
    _console.print(table)
    _console.print(
        f"\n{stats.docs_succeeded} succeeded · {stats.docs_failed} failed · "
        f"{stats.chunks_total} chunks · {stats.duration_ms} ms"
    )

    if stats.docs_failed > 0:
        raise typer.Exit(code=2)


# ──────────────────────────────────────────────────────────────────────────
#  kb-search (PR-5)
# ──────────────────────────────────────────────────────────────────────────


@app.command(name="kb-search")
def kb_search_cmd(
    query: str = typer.Argument(..., help="Search query."),  # noqa: B008
    top_k: int = typer.Option(5, "--top-k", "-k", help="Max number of hits."),
    namespace: str | None = typer.Option(None, "--namespace", help="Filter to a single namespace."),
    classification: str | None = typer.Option(
        None, "--classification", help="Filter to one classification level."
    ),
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04",
        "--embedding-model",
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
) -> None:
    """Hybrid (FTS5 + ANN) search over the KB; returns top-k chunks."""
    cfg = load_config()
    sqlite, lance = _open_kb_stores(
        home=cfg.home,
        embedding_dim=embedding_dim,
        embedding_model=embedding_model,
    )
    provider = make_provider("ollama-local")

    def embed_fn(text: str) -> list[float]:
        return provider.embed([text], model=embed_model_short)[0]

    hits = kb_search(
        query,
        sqlite=sqlite,
        lance=lance,
        embed_fn=embed_fn,
        top_k=top_k,
        namespace=namespace,
        classification=classification,
    )

    if not hits:
        _console.print("[yellow]No matches.[/yellow]")
        return

    table = Table(title=f"Top {len(hits)} hits for: {query}")
    table.add_column("#", justify="right")
    table.add_column("Chunk")
    table.add_column("Doc")
    table.add_column("RRF", justify="right")
    table.add_column("Ranks (V/F)", justify="right")
    table.add_column("Snippet", overflow="fold")

    for i, h in enumerate(hits, start=1):
        snippet = (h.content or "").strip().replace("\n", " ")[:80]
        ranks = f"{h.rank_vector or '-'}/{h.rank_fts or '-'}"
        table.add_row(
            str(i),
            h.chunk_id,
            h.document_id,
            f"{h.score:.4f}",
            ranks,
            snippet,
        )
    _console.print(table)


# ──────────────────────────────────────────────────────────────────────────
#  run (PR-7)
# ──────────────────────────────────────────────────────────────────────────


@app.command()
def run(
    playbook: Path = typer.Option(  # noqa: B008
        ...,
        "--playbook",
        "-p",
        exists=True,
        help="Path to the playbook directory (contains playbook.yaml + prompt.md).",
    ),
    input: Path = typer.Option(  # noqa: A002, B008
        ...,
        "--input",
        "-i",
        exists=True,
        help="Path to the input ticket JSON.",
    ),
    owner: str = typer.Option(
        "vicente@example.com",
        "--owner",
        help="Session owner (email/user id).",
    ),
    kb_id: str | None = typer.Option(
        None,
        "--kb-id",
        help="KB id; defaults to playbook.defaults.kb_id.",
    ),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        help="Override namespace; defaults to --kb-id.",
    ),
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04",
        "--embedding-model",
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
) -> None:
    """Run a playbook end-to-end against a ticket and emit a structured artifact."""
    cfg = load_config()
    pb = load_playbook(playbook)
    sqlite, lance = _open_kb_stores(
        home=cfg.home,
        embedding_dim=embedding_dim,
        embedding_model=embedding_model,
    )
    redactor = Redactor.from_yaml()
    provider = make_provider("ollama-local")

    def embed_fn(text: str) -> list[float]:
        return provider.embed([text], model=embed_model_short)[0]

    sm = SessionManager(home=cfg.home)
    request = RunRequest(
        playbook=pb,
        input_path=input,
        owner=owner,
        kb_id=kb_id,
        namespace=namespace,
    )
    result = run_ticket_summary(
        request,
        session_manager=sm,
        provider=provider,
        redactor=redactor,
        embed_fn=embed_fn,
        sqlite_store=sqlite,
        lance_store=lance,
    )

    table = Table(title=f"Run result · session {result.session_id}")
    table.add_column("Field")
    table.add_column("Value", overflow="fold")
    table.add_row("playbook", f"{pb.id}@{pb.version}")
    table.add_row("session_id", result.session_id)
    table.add_row("artifact_id", result.artifact_id or "-")
    table.add_row(
        "schema_valid",
        "[green]yes[/green]" if result.schema_valid else "[red]no[/red]",
    )
    if result.summary:
        table.add_row("work_item_ref", str(result.summary.get("work_item_ref", "?")))
        table.add_row(
            "summary",
            (result.summary.get("summary") or "")[:200],
        )
    if result.error:
        table.add_row("error", f"[red]{result.error}[/red]")
    _console.print(table)

    if not result.schema_valid:
        raise typer.Exit(code=2)


# ──────────────────────────────────────────────────────────────────────────
#  doc (vendor document generation)
# ──────────────────────────────────────────────────────────────────────────

doc_app = typer.Typer(
    name="doc",
    help="Vendor document generation from KB.",
    no_args_is_help=True,
)
app.add_typer(doc_app)

_VENDOR_DOC_PLAYBOOK_DIR = REPO_ROOT / "playbooks" / "pb_vendor_doc_en"


@doc_app.command("generate")
def doc_generate(
    topic: str = typer.Option(..., "--topic", "-t", help="Document topic."),
    template: str = typer.Option(
        "sop_summary",
        "--template",
        help="Template: sop_summary | maintenance_window | incident_report | handover",
    ),
    vendor: str = typer.Option("", "--vendor", "-v", help="Vendor name (optional)."),
    playbook: Path = typer.Option(  # noqa: B008
        _VENDOR_DOC_PLAYBOOK_DIR,
        "--playbook",
        "-p",
        help="Path to the playbook directory.",
    ),
    output: Path | None = typer.Option(  # noqa: B008
        None, "--output", "-o", help="Save result JSON to this path."
    ),
    owner: str = typer.Option("cli-user", "--owner"),
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04", "--embedding-model"
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
) -> None:
    """Generate a vendor-facing operational document from KB content."""
    cfg = load_config()
    pb = load_playbook(playbook)
    sqlite, lance = _open_kb_stores(
        home=cfg.home,
        embedding_dim=embedding_dim,
        embedding_model=embedding_model,
    )
    redactor = Redactor.from_yaml()
    provider = make_provider(
        pb.model.provider_id,
        kind=pb.model.kind,
        api_key=cfg.anthropic_api_key if pb.model.provider_id.startswith("anthropic") else None,
    )
    embed_provider = make_provider("ollama-local")

    def embed_fn(text: str) -> list[float]:
        return embed_provider.embed([text], model=embed_model_short)[0]

    sm = SessionManager(home=cfg.home)

    input_dict = {
        "topic": topic,
        "template_id": template,
        "vendor_name": vendor,
        "language": "en",
    }

    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(input_dict, f, ensure_ascii=False)
        input_path = Path(f.name)

    try:
        request = RunRequest(
            playbook=pb,
            input_path=input_path,
            owner=owner,
        )
        result = run_ticket_summary(
            request,
            session_manager=sm,
            provider=provider,
            redactor=redactor,
            embed_fn=embed_fn,
            sqlite_store=sqlite,
            lance_store=lance,
            user_msg_fn=_format_doc_request,
        )
    finally:
        input_path.unlink(missing_ok=True)

    table = Table(title=f"Vendor Doc · session {result.session_id}")
    table.add_column("Field")
    table.add_column("Value", overflow="fold")
    table.add_row("playbook", f"{pb.id}@{pb.version}")
    table.add_row("session_id", result.session_id)
    table.add_row("artifact_id", result.artifact_id or "-")
    table.add_row(
        "schema_valid",
        "[green]yes[/green]" if result.schema_valid else "[red]no[/red]",
    )
    if result.summary:
        table.add_row("doc_ref", str(result.summary.get("doc_ref", "?")))
        table.add_row("title", (result.summary.get("title") or "")[:120])
        sections = result.summary.get("sections") or []
        table.add_row("sections", str(len(sections)))
        citations = result.summary.get("citations") or []
        table.add_row("citations", str(len(citations)))
    if result.error:
        table.add_row("error", f"[red]{result.error}[/red]")
    _console.print(table)

    if output is not None and result.summary:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result.summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _console.print(f"\n[dim]Saved to {output}[/dim]")

    if not result.schema_valid:
        raise typer.Exit(code=2)


@doc_app.command("import-dir")
def doc_import_dir(
    directory: Path = typer.Argument(  # noqa: B008
        ..., help="Directory containing vendor doc .json files to import."
    ),
) -> None:
    """Copy pre-authored vendor doc .json files into ~/.opspilot/vendor-docs/."""
    cfg = load_config()
    vd_dir = cfg.home / "vendor-docs"
    vd_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(directory.rglob("*.json"))
    if not files:
        _err.print(f"[yellow]No .json files found under {directory}[/yellow]")
        raise typer.Exit(code=1)

    for json_file in files:
        dest = vd_dir / json_file.name
        dest.write_bytes(json_file.read_bytes())
        _console.print(f"  [green]✓[/green] {json_file.name}")

    _console.print(f"\n[bold]{len(files)}[/bold] vendor doc(s) imported to {vd_dir}")


# ──────────────────────────────────────────────────────────────────────────
#  harness (PR-8)
# ──────────────────────────────────────────────────────────────────────────


kb_app = typer.Typer(
    name="kb",
    help="Knowledge-base utilities (frozen-fixture loaders, future: stats / purge).",
    no_args_is_help=True,
)
app.add_typer(kb_app)


@kb_app.command("load-fixture")
def kb_load_fixture(
    doc_meta: Path = typer.Option(  # noqa: B008
        ..., "--doc-meta", "-d", exists=True, help="Path to doc-meta.json."
    ),
    chunks: Path = typer.Option(  # noqa: B008
        ..., "--chunks", "-c", exists=True, help="Path to chunks.jsonl."
    ),
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04", "--embedding-model"
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
) -> None:
    """Upsert a frozen KB fixture (doc-meta + chunks.jsonl) into ~/.opspilot/kb/.

    Bypasses the chunker / redactor / markitdown so spec-example fixtures
    keep their hand-authored chunk_id / document_id verbatim. The
    embedding for each chunk is produced live via the configured Ollama
    model so the live LanceDB table is consistent with retrieval.
    """
    cfg = load_config()
    sqlite, lance = _open_kb_stores(
        home=cfg.home,
        embedding_dim=embedding_dim,
        embedding_model=embedding_model,
    )
    provider = make_provider("ollama-local")

    def embed_fn(text: str) -> list[float]:
        return provider.embed([text], model=embed_model_short)[0]

    stats = load_kb_fixture(
        sqlite=sqlite,
        lance=lance,
        doc_meta_path=doc_meta,
        chunks_jsonl_path=chunks,
        embed_fn=embed_fn,
    )

    table = Table(title=f"KB fixture loaded · {stats.document_id}", show_lines=False)
    table.add_column("File", overflow="fold")
    table.add_column("Doc ID", overflow="fold")
    table.add_column("Chunks", justify="right")
    table.add_column("Vectors", justify="right")
    table.add_row(
        str(chunks.relative_to(REPO_ROOT) if chunks.is_relative_to(REPO_ROOT) else chunks),
        stats.document_id,
        str(stats.chunk_count),
        str(stats.vector_count),
    )
    _console.print(table)


@kb_app.command("load-dir")
def kb_load_dir(
    directory: Path = typer.Argument(  # noqa: B008
        ..., help="Root directory to search for doc-meta.json + chunks.jsonl pairs."
    ),
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04", "--embedding-model"
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
) -> None:
    """Recursively find and load all KB fixture pairs (doc-meta.json + chunks.jsonl) under DIRECTORY."""
    pairs: list[tuple[Path, Path]] = []
    for meta in sorted(directory.rglob("doc-meta.json")):
        chunks_path = meta.parent / "chunks.jsonl"
        if chunks_path.is_file():
            pairs.append((meta, chunks_path))

    if not pairs:
        _err.print(
            f"[yellow]No doc-meta.json + chunks.jsonl pairs found under {directory}[/yellow]"
        )
        raise typer.Exit(code=1)

    cfg = load_config()
    sqlite, lance = _open_kb_stores(
        home=cfg.home,
        embedding_dim=embedding_dim,
        embedding_model=embedding_model,
    )
    provider = make_provider("ollama-local")

    def embed_fn(text: str) -> list[float]:
        return provider.embed([text], model=embed_model_short)[0]

    table = Table(title=f"KB fixtures loaded from {directory}", show_lines=False)
    table.add_column("Doc ID", overflow="fold")
    table.add_column("Source", overflow="fold")
    table.add_column("Chunks", justify="right")
    table.add_column("Vectors", justify="right")

    failed = 0
    for meta, chunks_path in pairs:
        try:
            stats = load_kb_fixture(
                sqlite=sqlite,
                lance=lance,
                doc_meta_path=meta,
                chunks_jsonl_path=chunks_path,
                embed_fn=embed_fn,
            )
            rel = str(
                chunks_path.relative_to(REPO_ROOT)
                if chunks_path.is_relative_to(REPO_ROOT)
                else chunks_path
            )
            table.add_row(stats.document_id, rel, str(stats.chunk_count), str(stats.vector_count))
        except Exception as e:  # noqa: BLE001
            _err.print(f"[red]failed:[/red] {meta} — {e}")
            failed += 1

    _console.print(table)
    if failed:
        _err.print(f"[red]{failed} fixture(s) failed[/red]")
        raise typer.Exit(code=1)


@kb_app.command("conflicts")
def kb_conflicts_cmd(
    status: str = typer.Option("open", "--status", "-s", help="Filter by status (open/all)."),
    limit: int = typer.Option(50, "--limit", "-n", help="Max rows to display."),
) -> None:
    """List KB conflict records detected during ingestion."""
    cfg = load_config()
    sqlite, _ = _open_kb_stores(home=cfg.home, embedding_dim=768, embedding_model="")
    rows = sqlite.list_conflicts(
        status=None if status == "all" else status,
        limit=limit,
    )
    if not rows:
        _console.print(f"[green]No conflicts with status={status!r}.[/green]")
        return
    table = Table(title=f"KB Conflicts (status={status})", show_lines=True)
    table.add_column("ID", overflow="fold")
    table.add_column("Type")
    table.add_column("Sim", justify="right")
    table.add_column("Status")
    table.add_column("Doc A")
    table.add_column("Doc B")
    for r in rows:
        table.add_row(
            r["id"],
            r["conflict_type"],
            f"{r['similarity']:.3f}",
            r["status"],
            r.get("doc_a_title") or r["doc_a_id"],
            r.get("doc_b_title") or r["doc_b_id"],
        )
    _console.print(table)


@kb_app.command("resolve")
def kb_resolve_cmd(
    conflict_id: str = typer.Argument(..., help="Conflict ID (conf_xxxxxxxx)."),
    resolution: str = typer.Option(
        ...,
        "--resolution",
        "-r",
        help="Resolution: a_wins | b_wins | merged | dismissed",
    ),
    resolved_by: str = typer.Option("", "--by", help="Who is resolving; defaults to the OS user."),
    note: str = typer.Option("", "--note", "-m", help="Optional resolution note."),
) -> None:
    """Apply a resolution to an open KB conflict."""
    cfg = load_config()
    sqlite, _ = _open_kb_stores(home=cfg.home, embedding_dim=768, embedding_model="")
    try:
        resolve_conflict(
            conflict_id,
            resolution=resolution,
            resolved_by=resolved_by or _cli_actor(),
            note=note,
            sqlite=sqlite,
        )
        _console.print(f"[green]Conflict {conflict_id} resolved as {resolution!r}.[/green]")
    except (ValueError, KeyError) as e:
        _console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e


@kb_app.command("correct")
def kb_correct_cmd(
    chunk_id: str = typer.Argument(..., help="Chunk ID (chk_xxxxxxxx)."),
    new_content: str = typer.Option(..., "--content", "-c", help="Corrected chunk content."),
    reason: str = typer.Option(..., "--reason", "-m", help="Why this correction is needed."),
    corrected_by: str = typer.Option(
        "", "--by", help="Who is applying the correction; defaults to the OS user."
    ),
) -> None:
    """Apply an inline content correction to a KB chunk."""
    cfg = load_config()
    sqlite, _ = _open_kb_stores(home=cfg.home, embedding_dim=768, embedding_model="")
    try:
        corr_id = sqlite.add_correction(
            chunk_id,
            corrected_by=corrected_by or _cli_actor(),
            reason=reason,
            new_content=new_content,
        )
        _console.print(f"[green]Correction {corr_id} applied to {chunk_id}.[/green]")
    except KeyError as e:
        _console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e


@kb_app.command("corrections")
def kb_corrections_cmd(
    chunk_id: str = typer.Option("", "--chunk", "-c", help="Filter to a specific chunk ID."),
    limit: int = typer.Option(50, "--limit", "-n", help="Max rows to display."),
) -> None:
    """List KB correction records."""
    cfg = load_config()
    sqlite, _ = _open_kb_stores(home=cfg.home, embedding_dim=768, embedding_model="")
    rows = sqlite.list_corrections(chunk_id=chunk_id or None, limit=limit)
    if not rows:
        _console.print("[green]No corrections recorded.[/green]")
        return
    table = Table(title="KB Corrections", show_lines=True)
    table.add_column("ID")
    table.add_column("Chunk")
    table.add_column("By")
    table.add_column("Reason")
    table.add_column("Created")
    for r in rows:
        table.add_row(
            r["id"],
            r["chunk_id"],
            r["corrected_by"],
            (r["reason"] or "")[:60],
            (r["created_at"] or "")[:19],
        )
    _console.print(table)


harness_app = typer.Typer(
    name="harness",
    help="Evaluation harness: run fixtures, compute scores, emit results.jsonl.",
    no_args_is_help=True,
)
app.add_typer(harness_app)


GOLDEN_FIXTURE_PATH = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "harness" / "fixture.json"
GOLDEN_GOLDEN_PATH = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "harness" / "golden.json"
GOLDEN_PLAYBOOK_DIR = REPO_ROOT / "playbooks" / "pb_ticket_summary_zh"

GEMINI_FIXTURE_PATH = GOLDEN_FIXTURE_PATH  # same ticket, same KB
GEMINI_GOLDEN_PATH = GOLDEN_GOLDEN_PATH
GEMINI_PLAYBOOK_DIR = REPO_ROOT / "playbooks" / "pb_ticket_summary_zh_gemini"
GEMINI_RESULTS_PATH = (
    REPO_ROOT / "examples" / "scn_ticket_summary_zh_gemini" / "harness" / "results.jsonl"
)

OPENROUTER_FIXTURE_PATH = GOLDEN_FIXTURE_PATH  # same ticket, same KB
OPENROUTER_GOLDEN_PATH = GOLDEN_GOLDEN_PATH
OPENROUTER_PLAYBOOK_DIR = REPO_ROOT / "playbooks" / "pb_ticket_summary_zh_openrouter"
OPENROUTER_RESULTS_PATH = (
    REPO_ROOT / "examples" / "scn_ticket_summary_zh_openrouter" / "harness" / "results.jsonl"
)

VENDOR_DOC_FIXTURE_PATH = REPO_ROOT / "examples" / "scn_vendor_doc_en" / "harness" / "fixture.json"
VENDOR_DOC_GOLDEN_PATH = REPO_ROOT / "examples" / "scn_vendor_doc_en" / "harness" / "golden.json"
VENDOR_DOC_PLAYBOOK_DIR = REPO_ROOT / "playbooks" / "pb_vendor_doc_en"
VENDOR_DOC_RESULTS_PATH = REPO_ROOT / "examples" / "scn_vendor_doc_en" / "harness" / "results.jsonl"


def _harness_dispatch(
    *,
    fixture_path: Path,
    golden_path: Path,
    playbook_dir: Path,
    owner: str,
    embedding_model: str,
    embedding_dim: int,
    embed_model_short: str,
    output: Path | None,
    user_msg_fn: Callable[[dict[str, Any]], str] | None = None,
    model_override: Model | None = None,
) -> int:
    """Shared entrypoint for both ``run`` and ``golden`` subcommands.

    When ``model_override`` is given the loaded playbook's chat model is
    swapped for it (used by ``golden-provider`` to exercise the same
    fixture across providers). Returns the desired CLI exit code.
    """
    cfg = load_config()
    fixture = load_fixture(fixture_path)
    golden = load_golden(golden_path)
    playbook = load_playbook(playbook_dir)
    if model_override is not None:
        playbook = dataclasses.replace(playbook, model=model_override)

    sqlite, lance = _open_kb_stores(
        home=cfg.home,
        embedding_dim=embedding_dim,
        embedding_model=embedding_model,
    )
    redactor = Redactor.from_yaml()
    chat_provider = make_provider(
        playbook.model.provider_id,
        kind=playbook.model.kind,
        api_key=cfg.anthropic_api_key
        if playbook.model.provider_id.startswith("anthropic")
        else None,
    )
    # Embed provider: always Ollama (other providers don't support embeddings)
    embed_provider = make_provider("ollama-local")
    sm = __import__("opspilot.session", fromlist=["SessionManager"]).SessionManager(home=cfg.home)

    def embed_fn(text: str) -> list[float]:
        return embed_provider.embed([text], model=embed_model_short)[0]

    result = run_harness(
        fixture=fixture,
        golden=golden,
        playbook=playbook,
        session_manager=sm,
        provider=chat_provider,
        redactor=redactor,
        embed_fn=embed_fn,
        sqlite_store=sqlite,
        lance_store=lance,
        owner=owner,
        user_msg_fn=user_msg_fn,
    )

    render_result_table(result, console=_console)

    # Emit results.jsonl row.
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result.to_dict(), ensure_ascii=False))
            f.write("\n")
        _console.print(f"\n[dim]appended result to {output}[/dim]")

    # Validate against eval-result.schema.json so the harness output is
    # always introspectable by `opspilot validate`.
    try:
        schema_validate("eval-result", result.to_dict())
    except Exception as e:  # noqa: BLE001
        _err.print(f"[red]eval-result schema invalid:[/red] {e}")
        return 3

    if not result.passed:
        return 2
    return 0


@harness_app.command("run")
def harness_run(
    fixture: Path = typer.Option(  # noqa: B008
        ..., "--fixture", "-f", exists=True, help="Path to fixture.json."
    ),
    golden: Path = typer.Option(  # noqa: B008
        ..., "--golden", "-g", exists=True, help="Path to golden.json."
    ),
    playbook: Path = typer.Option(  # noqa: B008
        ..., "--playbook", "-p", exists=True, help="Path to playbook directory."
    ),
    owner: str = typer.Option("harness@opspilot", "--owner"),
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04", "--embedding-model"
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        help="Append result row to this results.jsonl path.",
    ),
) -> None:
    """Run a single fixture and report scores."""
    code = _harness_dispatch(
        fixture_path=fixture,
        golden_path=golden,
        playbook_dir=playbook,
        owner=owner,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embed_model_short=embed_model_short,
        output=output,
    )
    if code != 0:
        raise typer.Exit(code=code)


@harness_app.command("golden")
def harness_golden(
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04", "--embedding-model"
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        help="Append result row to this results.jsonl path.",
    ),
) -> None:
    """Run the Stage 1 golden test (scn_ticket_summary_zh)."""
    if not GOLDEN_FIXTURE_PATH.is_file():
        _err.print(f"[red]golden fixture not found:[/red] {GOLDEN_FIXTURE_PATH}")
        raise typer.Exit(code=1)
    code = _harness_dispatch(
        fixture_path=GOLDEN_FIXTURE_PATH,
        golden_path=GOLDEN_GOLDEN_PATH,
        playbook_dir=GOLDEN_PLAYBOOK_DIR,
        owner="harness@opspilot",
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embed_model_short=embed_model_short,
        output=output,
    )
    if code != 0:
        raise typer.Exit(code=code)


@harness_app.command("golden-gemini")
def harness_golden_gemini(
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04", "--embedding-model"
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        help="Append result row to this results.jsonl path (default: examples/scn_ticket_summary_zh_gemini/harness/results.jsonl).",
    ),
) -> None:
    """Run the Stage 5 Gemini golden test (scn_ticket_summary_zh via Gemini API).

    Requires GEMINI_API_KEY to be set. Passes when weighted_score is within
    delta < 0.1 of the Anthropic baseline (0.968).
    """
    if not GEMINI_FIXTURE_PATH.is_file():
        _err.print(f"[red]fixture not found:[/red] {GEMINI_FIXTURE_PATH}")
        raise typer.Exit(code=1)
    resolved_output = output or GEMINI_RESULTS_PATH
    code = _harness_dispatch(
        fixture_path=GEMINI_FIXTURE_PATH,
        golden_path=GEMINI_GOLDEN_PATH,
        playbook_dir=GEMINI_PLAYBOOK_DIR,
        owner="harness@opspilot",
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embed_model_short=embed_model_short,
        output=resolved_output,
    )
    if code != 0:
        raise typer.Exit(code=code)


@harness_app.command("golden-openrouter")
def harness_golden_openrouter(
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04", "--embedding-model"
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        help="Append result row to this results.jsonl path (default: examples/scn_ticket_summary_zh_openrouter/harness/results.jsonl).",
    ),
) -> None:
    """Run the Stage 4 OpenRouter golden test (scn_ticket_summary_zh via OpenRouter).

    Requires OPENROUTER_API_KEY to be set. Passes when weighted_score is within
    delta < 0.1 of the Anthropic baseline (0.968).
    """
    if not OPENROUTER_FIXTURE_PATH.is_file():
        _err.print(f"[red]fixture not found:[/red] {OPENROUTER_FIXTURE_PATH}")
        raise typer.Exit(code=1)
    resolved_output = output or OPENROUTER_RESULTS_PATH
    code = _harness_dispatch(
        fixture_path=OPENROUTER_FIXTURE_PATH,
        golden_path=OPENROUTER_GOLDEN_PATH,
        playbook_dir=OPENROUTER_PLAYBOOK_DIR,
        owner="harness@opspilot",
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embed_model_short=embed_model_short,
        output=resolved_output,
    )
    if code != 0:
        raise typer.Exit(code=code)


def _infer_model_kind(provider_id: str) -> str:
    """Map a provider id to a Model.kind (mirrors providers.registry)."""
    if provider_id.startswith("anthropic"):
        return "anthropic"
    if provider_id.startswith("ollama"):
        return "ollama"
    return "openai"


@harness_app.command("golden-provider")
def harness_golden_provider(
    provider: str = typer.Option(
        ..., "--provider", help="Provider id, e.g. openai / grok / ollama-local."
    ),
    model: str = typer.Option(..., "--model", help="Chat model name for the provider."),
    kind: str | None = typer.Option(
        None, "--kind", help="Provider kind; inferred from the provider id when omitted."
    ),
    model_version: str = typer.Option(
        "current", "--model-version", help="Model version tag (provenance only)."
    ),
    temperature: float | None = typer.Option(
        None, "--temperature", help="Sent only when given; current Anthropic models reject it."
    ),
    top_p: float | None = typer.Option(None, "--top-p", help="Sent only when given."),
    max_tokens: int = typer.Option(4096, "--max-tokens"),
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04", "--embedding-model"
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        help="Append result row to this results.jsonl path.",
    ),
) -> None:
    """Run the Stage 1 golden fixture against an arbitrary chat provider.

    Reuses the base ``pb_ticket_summary_zh`` playbook (retrieval.mode=prefetch)
    and only swaps the chat model, so any of the 6 providers can be exercised
    on the same fixture without a dedicated playbook. Drives ``make
    harness-matrix``. Requires the provider's API key env var (and Ollama for
    embeddings).
    """
    if not GOLDEN_FIXTURE_PATH.is_file():
        _err.print(f"[red]golden fixture not found:[/red] {GOLDEN_FIXTURE_PATH}")
        raise typer.Exit(code=1)
    resolved_kind: Any = kind or _infer_model_kind(provider)
    # Sampling knobs are sent only when asked for. Hardcoding temperature=0.2
    # here meant `--model claude-sonnet-5` swapped the name but kept a parameter
    # that model rejects: the primary 400'd and the fallback quietly answered,
    # so the row measured a different model than the one on the flag (#175).
    params: dict[str, Any] = {"max_tokens": max_tokens}
    if temperature is not None:
        params["temperature"] = temperature
    if top_p is not None:
        params["top_p"] = top_p
    model_override = Model(
        provider_id=provider,
        kind=resolved_kind,
        name=model,
        version=model_version,
        params=params,
    )
    code = _harness_dispatch(
        fixture_path=GOLDEN_FIXTURE_PATH,
        golden_path=GOLDEN_GOLDEN_PATH,
        playbook_dir=GOLDEN_PLAYBOOK_DIR,
        owner="harness@opspilot",
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embed_model_short=embed_model_short,
        output=output,
        model_override=model_override,
    )
    if code != 0:
        raise typer.Exit(code=code)


@harness_app.command("golden-vendor-doc")
def harness_golden_vendor_doc(
    embedding_model: str = typer.Option(
        "ollama-local/nomic-embed-text-v2-moe@2026-04", "--embedding-model"
    ),
    embedding_dim: int = typer.Option(768, "--embedding-dim"),
    embed_model_short: str = typer.Option("nomic-embed-text-v2-moe", "--ollama-embed-model"),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        help="Append result row to this results.jsonl path.",
    ),
) -> None:
    """Run the vendor-doc golden test (scn_vendor_doc_en)."""
    if not VENDOR_DOC_FIXTURE_PATH.is_file():
        _err.print(f"[red]fixture not found:[/red] {VENDOR_DOC_FIXTURE_PATH}")
        raise typer.Exit(code=1)
    resolved_output = output or VENDOR_DOC_RESULTS_PATH
    code = _harness_dispatch(
        fixture_path=VENDOR_DOC_FIXTURE_PATH,
        golden_path=VENDOR_DOC_GOLDEN_PATH,
        playbook_dir=VENDOR_DOC_PLAYBOOK_DIR,
        owner="harness@opspilot",
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embed_model_short=embed_model_short,
        output=resolved_output,
        user_msg_fn=_format_doc_request,
    )
    if code != 0:
        raise typer.Exit(code=code)


# ──────────────────────────────────────────────────────────────────────────
#  wiki (PR-19 / PR-24)
# ──────────────────────────────────────────────────────────────────────────

wiki_app = typer.Typer(
    name="wiki",
    help="Wiki operations: ingest KB docs into wiki pages; query→page conversion.",
    no_args_is_help=True,
)
app.add_typer(wiki_app)


@wiki_app.command("ingest")
def wiki_ingest(
    doc_id: str = typer.Argument(..., help="KB document ID (doc_<sha8>) to ingest."),
    wiki_root: Path = typer.Option(  # noqa: B008
        Path("wiki"),
        "--wiki-root",
        help="Path to the wiki/ directory.",
    ),
    model: str = typer.Option(
        "qwen2.5:7b",
        "--model",
        help="Ollama model name for page generation.",
    ),
    base_url: str = typer.Option(
        "http://localhost:11434",
        "--base-url",
        help="Ollama API base URL.",
    ),
    owner: str = typer.Option("wiki-maintainer@opspilot", "--owner"),
    namespace: str = typer.Option("opspilot:public-kb", "--namespace"),
    db_path: Path = typer.Option(  # noqa: B008
        None, "--db", help="SQLite KB path (default: ~/.opspilot/kb/kb.sqlite)."
    ),
) -> None:
    """Generate a wiki summary page from an already-ingested KB document."""
    cfg = load_config()
    kb_dir = cfg.home / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = db_path or (kb_dir / "sqlite.db")

    from .providers.ollama import OllamaProvider

    provider = OllamaProvider(base_url=base_url)

    with SqliteStore(init_sqlite(sqlite_path)) as sqlite:
        wiki_cfg = WikiIngestConfig(
            wiki_root=wiki_root,
            namespace=namespace,
            owner=owner,
            model=model,
        )
        result = run_wiki_ingest(doc_id, sqlite=sqlite, provider=provider, config=wiki_cfg)

    _console.print(f"[green]✓[/green] Created wiki page: {result.page_path}")
    _console.print(f"  page_id : {result.page_id}")
    _console.print(f"  slug    : {result.slug}")
    _console.print(f"  created : {result.pages_created}  updated : {result.pages_updated}")


@wiki_app.command("query-to-page")
def wiki_query_to_page(
    session_id: str | None = typer.Option(  # noqa: UP007
        None,
        "--session",
        "-s",
        help="Convert a specific session ID. Omit to scan recent sessions.",
    ),
    wiki_root: Path = typer.Option(  # noqa: B008
        Path("wiki"),
        "--wiki-root",
        help="Path to the wiki/ directory.",
    ),
    model: str = typer.Option(
        "qwen2.5:7b",
        "--model",
        help="Ollama model name for page drafting.",
    ),
    base_url: str = typer.Option(
        "http://localhost:11434",
        "--base-url",
        help="Ollama API base URL.",
    ),
    owner: str = typer.Option("wiki-maintainer@opspilot", "--owner"),
    namespace: str = typer.Option("opspilot:public-kb", "--namespace"),
    max_sessions: int = typer.Option(50, "--max-sessions", help="Max sessions to scan."),
) -> None:
    """Convert qualifying session responses into wiki synthesis pages (PR-24).

    Use --session to convert one specific session, or omit to scan and
    convert all qualifying recent sessions.
    """
    from .providers.ollama import OllamaProvider
    from .wiki.query_to_page import QueryToPageConfig, scan_and_convert
    from .wiki.query_to_page import query_to_page as _q2p

    cfg = load_config()
    sm = SessionManager(home=cfg.home)
    provider = OllamaProvider(base_url=base_url)
    q2p_cfg = QueryToPageConfig(
        wiki_root=wiki_root,
        namespace=namespace,
        owner=owner,
        model=model,
    )

    if session_id:
        results = [_q2p(session_id, session_manager=sm, provider=provider, config=q2p_cfg)]
    else:
        results = scan_and_convert(
            session_manager=sm,
            provider=provider,
            config=q2p_cfg,
            max_sessions=max_sessions,
        )

    table = Table(title="Query→Page results", show_lines=False)
    table.add_column("Session", overflow="fold")
    table.add_column("Slug", overflow="fold")
    table.add_column("Trigger")
    table.add_column("Status", justify="right")

    for r in results:
        if r.skipped:
            status = f"[dim]skipped: {r.skip_reason[:60]}[/dim]"
        else:
            status = "[green]✓ created[/green]"
        table.add_row(r.session_id[:24], r.slug or "—", r.trigger or "—", status)

    _console.print(table)
    created = sum(1 for r in results if not r.skipped)
    _console.print(f"\n{created} page(s) created · {len(results) - created} skipped")


@wiki_app.command("promote")
def wiki_promote(
    slug: str = typer.Argument(help="Page slug to promote."),
    wiki_root: Path = typer.Option(  # noqa: B008
        Path("wiki"),
        "--wiki-root",
        help="Path to the wiki/ directory.",
    ),
    to: str = typer.Option(
        "live",
        "--to",
        help="Target lifecycle state: reviewed | live | stale | archived.",
    ),
) -> None:
    """Advance a wiki page's lifecycle state (PR-25).

    Examples::

        opspilot wiki promote my-page-slug
        opspilot wiki promote my-page-slug --to reviewed
        opspilot wiki promote my-page-slug --to stale
    """
    from .wiki.promote import PromoteConfig, PromoteError
    from .wiki.promote import promote_page as _promote

    cfg = PromoteConfig(wiki_root=wiki_root, target_state=to)
    try:
        result = _promote(slug, cfg)
    except PromoteError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if result.skipped:
        _console.print(f"[yellow]Skipped:[/yellow] {result.skip_reason}")
    else:
        _console.print(
            f"[green]✓[/green] {slug}: {result.old_state} → {result.new_state}"
            f"  (v{result.new_version})"
        )
        _console.print(f"  path: {result.page_path}")


@wiki_app.command("import-dir")
def wiki_import_dir(
    directory: Path = typer.Argument(  # noqa: B008
        ..., help="Directory containing pre-authored wiki .md page files."
    ),
    wiki_root: Path = typer.Option(  # noqa: B008
        None, "--wiki-root", help="Wiki root (default: ~/.opspilot/wiki)."
    ),
) -> None:
    """Copy pre-authored wiki .md files into ~/.opspilot/wiki/pages/."""
    cfg = load_config()
    pages_dir = (wiki_root or cfg.home / "wiki") / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(directory.rglob("*.md"))
    if not files:
        _err.print(f"[yellow]No .md files found under {directory}[/yellow]")
        raise typer.Exit(code=1)

    for md_file in files:
        dest = pages_dir / md_file.name
        dest.write_bytes(md_file.read_bytes())
        _console.print(f"  [green]✓[/green] {md_file.name}")

    _console.print(f"\n[bold]{len(files)}[/bold] page(s) imported to {pages_dir}")


# ──────────────────────────────────────────────────────────────────────────
#  iteration (PR-27)
# ──────────────────────────────────────────────────────────────────────────

iteration_app = typer.Typer(
    name="iteration",
    help="Skill iteration: feedback aggregation, variant evaluation, promotion.",
    no_args_is_help=True,
)
app.add_typer(iteration_app)


@iteration_app.command("sense")
def iteration_sense(
    signals: Path = typer.Argument(  # noqa: B008
        ..., exists=True, help="Path to feedback/signals.jsonl."
    ),
    threshold: float = typer.Option(
        5.0, "--threshold", "-t", help="Trigger threshold (default: 5.0)."
    ),
    window_days: int = typer.Option(30, "--window-days", help="Feedback window in days."),
) -> None:
    """Compute aggregate feedback weight and report should_trigger."""
    policy = IterationPolicy(
        feedback_min_weight_to_trigger=threshold, feedback_window_days=window_days
    )
    engine = IterationEngine(policy=policy)
    result = engine.sense(signals)

    _console.print(f"skill_ref         : {result.skill_ref}")
    _console.print(f"window_days       : {result.window_days}")
    _console.print(f"signals_in_window : {result.signal_count}")
    _console.print(f"aggregate_weight  : {result.aggregate_weight}")
    _console.print(f"threshold         : {result.threshold}")
    color = "green" if result.should_trigger else "yellow"
    _console.print(f"should_trigger    : [{color}]{result.should_trigger}[/{color}]")
    if not result.should_trigger:
        raise typer.Exit(code=1)


@iteration_app.command("evaluate")
def iteration_evaluate(
    iteration_dir: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        help="Path to iteration example directory (contains iteration/ + eval/ + variants/).",
    ),
    min_delta: float = typer.Option(
        0.01, "--min-delta", help="Minimum weighted score delta to pass."
    ),
    max_cost_pct: float = typer.Option(10.0, "--max-cost-pct", help="Max cost increase % allowed."),
) -> None:
    """Apply promotion gates to pre-computed eval results and show verdicts."""
    policy = IterationPolicy(min_delta_weighted=min_delta, max_cost_increase_pct=max_cost_pct)
    engine = IterationEngine(policy=policy)
    verdicts = engine.evaluate(iteration_dir)

    table = Table(title="Variant verdicts", show_lines=False)
    table.add_column("Variant ID")
    table.add_column("Δweighted", justify="right")
    table.add_column("Δcost %", justify="right")
    table.add_column("Verdict")
    table.add_column("Reasons", overflow="fold")

    all_winning = True
    for v in verdicts:
        color = "green" if v.gate.verdict == "winning" else "red"
        if v.gate.verdict != "winning":
            all_winning = False
        table.add_row(
            v.variant_id,
            f"{v.delta.weighted:+.3f}",
            f"{v.delta.cost_pct:+.1f}",
            f"[{color}]{v.gate.verdict}[/{color}]",
            "; ".join(v.verdict_reasons),
        )

    _console.print(table)
    if not all_winning:
        raise typer.Exit(code=1)


@iteration_app.command("promote")
def iteration_promote(
    iteration_dir: Path = typer.Argument(  # noqa: B008
        ..., exists=True, help="Path to iteration example directory."
    ),
    variant_id: str = typer.Argument(..., help="Variant ID to promote (e.g. var_9930d615)."),
    new_version: str = typer.Option(..., "--version", "-v", help="New skill version (e.g. 1.3.0)."),
    summary: str = typer.Option(..., "--summary", "-s", help="Summary sentence for lineage entry."),
    actor: str = typer.Option("human@opspilot", "--actor", help="Approver identity."),
    lineage_file: Path | None = typer.Option(  # noqa: B008
        None,
        "--lineage",
        "-l",
        help="Path to lineage YAML to update. Skipped if omitted.",
    ),
) -> None:
    """Promote a variant: copy SKILL.md → promoted/ and append lineage entry."""
    engine = IterationEngine()
    engine.promote(
        iteration_dir=iteration_dir,
        variant_id=variant_id,
        actor=actor,
        new_version=new_version,
        summary=summary,
        lineage_file=lineage_file,
    )
    _console.print(f"[green]✓[/green] Promoted {variant_id} → v{new_version}")
    _console.print(f"  promoted/SKILL.md written to {iteration_dir / 'promoted' / 'SKILL.md'}")
    if lineage_file:
        _console.print(f"  lineage entry appended to {lineage_file}")


@iteration_app.command("validate")
def iteration_validate(
    iteration_dir: Path = typer.Argument(  # noqa: B008
        ..., exists=True, help="Path to iteration example directory."
    ),
) -> None:
    """Validate all invariants in an iteration directory (checksums, IDs, lineage)."""
    engine = IterationEngine()
    violations = engine.validate(iteration_dir)
    if violations:
        for v in violations:
            _err.print(f"[red]✗[/red] {v}")
        raise typer.Exit(code=1)
    _console.print(f"[green]✓[/green] All invariants pass for {iteration_dir}")


# ──────────────────────────────────────────────────────────────────────────
#  mcp (PR-31)
# ──────────────────────────────────────────────────────────────────────────

_DEFAULT_MCP_CONFIG = Path("mcp-config.yaml")

mcp_app = typer.Typer(
    name="mcp",
    help="MCP client — list servers/tools and probe health (PR-31).",
    no_args_is_help=True,
)
app.add_typer(mcp_app)


@mcp_app.command("list")
def mcp_list(
    config: Path = typer.Option(  # noqa: B008
        _DEFAULT_MCP_CONFIG, "--config", "-c", help="Path to mcp-config.yaml."
    ),
) -> None:
    """List registered MCP servers and their tools (connects to enabled servers)."""
    from .mcp import McpRegistry, load_mcp_config

    cfg = load_mcp_config(config)
    registry = McpRegistry.from_config(cfg)

    table = Table(title=f"MCP servers ({config})", show_lines=True)
    table.add_column("ID", style="cyan")
    table.add_column("Transport")
    table.add_column("Enabled")
    table.add_column("Tools prefix")
    table.add_column("Trust")

    for srv in cfg.mcps:
        table.add_row(
            srv.id,
            srv.transport,
            "[green]yes[/green]" if srv.enabled else "[dim]no[/dim]",
            srv.tools_prefix,
            srv.trust,
        )
    _console.print(table)

    enabled = [s for s in cfg.mcps if s.enabled]
    if not enabled:
        _console.print("[dim]No enabled servers.[/dim]")
        return

    _console.print("\n[bold]Connecting to enabled servers to list tools…[/bold]")
    try:
        tools_by_server = registry.refresh_all_tools()
    except Exception as exc:  # noqa: BLE001
        _err.print(f"[yellow]Warning:[/yellow] {exc}")
        return
    finally:
        registry.close_all()

    for server_id, tools in tools_by_server.items():
        if not tools:
            _console.print(f"  [dim]{server_id}: no tools (or allowlist filtered all)[/dim]")
            continue
        _console.print(f"  [cyan]{server_id}[/cyan]: {len(tools)} tool(s)")
        for t in tools:
            _console.print(f"    • {t.name}  {t.description[:60]}")


@mcp_app.command("probe")
def mcp_probe(
    server_id: str = typer.Argument(..., help="Server ID to probe."),
    config: Path = typer.Option(  # noqa: B008
        _DEFAULT_MCP_CONFIG, "--config", "-c", help="Path to mcp-config.yaml."
    ),
) -> None:
    """Probe a single MCP server — connect, list tools, and report health."""
    from .mcp import load_mcp_config
    from .mcp.registry import McpServerClient

    cfg = load_mcp_config(config)
    srv_cfg = next((s for s in cfg.mcps if s.id == server_id), None)
    if srv_cfg is None:
        _err.print(f"[red]Server '{server_id}' not found in config.[/red]")
        raise typer.Exit(1)

    client = McpServerClient(srv_cfg)
    try:
        tools = client.refresh_tools()
        color = "green"
        _console.print(f"[{color}]✓[/{color}] {server_id}: {len(tools)} tool(s) available")
        for t in tools:
            _console.print(f"  • {t.name}  {t.description[:72]}")
    except Exception as exc:  # noqa: BLE001
        _err.print(f"[red]✗[/red] {server_id}: {exc}")
        raise typer.Exit(1) from exc
    finally:
        client.close()


# ──────────────────────────────────────────────────────────────────────────
#  sandbox (PR-30)
# ──────────────────────────────────────────────────────────────────────────

sandbox_app = typer.Typer(
    name="sandbox",
    help="Sandbox action execution — L2 Docker hardened / L3 gVisor (PR-30, ADR-0009).",
    no_args_is_help=True,
)
app.add_typer(sandbox_app)


def _load_action(path: Path) -> ActionRequest:
    import yaml

    from .sandbox.types import ActionRequest

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ActionRequest.model_validate(raw)


def _parse_level(level: str) -> Literal["l2", "l3"]:
    norm = level.strip().lower()
    if norm not in ("l2", "l3"):
        _err.print(f"[red]✗[/red] invalid --level {level!r}; expected 'l2' or 'l3'")
        raise typer.Exit(2)
    return cast('Literal["l2", "l3"]', norm)


@sandbox_app.command("dry-run")
def sandbox_dry_run(
    action: Path = typer.Argument(..., exists=True, help="Action YAML file."),  # noqa: B008
    level: str = typer.Option("l2", "--level", help="Isolation backend: l2 | l3 (gVisor)."),
) -> None:
    """Preview a sandbox action without executing it."""
    from rich.syntax import Syntax

    from .sandbox.engine import SandboxEngine

    req = _load_action(action)
    result = SandboxEngine(level=_parse_level(level)).dry_run(req)

    _console.print(f"\n[bold]Action[/bold] {result.action_id}  status=[cyan]{result.status}[/cyan]")
    if result.approval_required:
        _console.print("[yellow]⚠ approval_required[/yellow]")
    if result.dry_run_preview:
        _console.print(f"\n[dim]{result.dry_run_preview.command_preview}[/dim]")
        _console.print(
            Syntax(
                "\n".join(result.dry_run_preview.docker_args),
                "text",
                theme="monokai",
                word_wrap=True,
            )
        )


@sandbox_app.command("run")
def sandbox_run(
    action: Path = typer.Argument(..., exists=True, help="Action YAML file."),  # noqa: B008
    approve: bool = typer.Option(False, "--approve", help="Bypass approval gate."),
    level: str = typer.Option("l2", "--level", help="Isolation backend: l2 | l3 (gVisor)."),
) -> None:
    """Execute a sandbox action in a Docker L2 (hardened) or L3 (gVisor) container."""
    from .sandbox.engine import SandboxEngine

    req = _load_action(action)
    result = SandboxEngine(level=_parse_level(level)).execute(req, force_approve=approve)

    _console.print(f"\n[bold]Action[/bold] {result.action_id}  status=[cyan]{result.status}[/cyan]")

    if result.status == "approval_pending":
        _err.print(f"[yellow]⚠[/yellow] {result.rejection_reason}")
        raise typer.Exit(2)

    if result.apply_result:
        r = result.apply_result
        color = "green" if r.exit_code == 0 else "red"
        _console.print(f"exit_code=[{color}]{r.exit_code}[/{color}]  duration={r.duration_ms}ms")
        if r.stdout:
            _console.print("\n[bold]stdout[/bold]")
            _console.print(r.stdout)
        if r.stderr:
            _console.print("\n[bold]stderr[/bold]")
            _console.print(r.stderr)
        if r.exit_code != 0:
            raise typer.Exit(1)


# ──────────────────────────────────────────────────────────────────────────
#  tui (PR-20 / PR-22)
# ──────────────────────────────────────────────────────────────────────────

tui_app = typer.Typer(
    name="tui",
    help="Terminal UI: browse sessions, KB, wiki; run playbooks interactively.",
    no_args_is_help=False,
    invoke_without_command=True,
)
app.add_typer(tui_app)


@tui_app.callback(invoke_without_command=True)
def tui(ctx: typer.Context) -> None:
    """Launch the OpsPilot terminal UI."""
    if ctx.invoked_subcommand is None:
        from .tui import run_tui

        run_tui()


@tui_app.command("run")
def tui_run(
    input: Path = typer.Option(  # noqa: A002, B008
        ...,
        "--input",
        "-i",
        help="Path to the input ticket JSON.",
    ),
    playbook: Path = typer.Option(  # noqa: B008
        Path("playbooks/pb_ticket_summary_zh"),
        "--playbook",
        "-p",
        help="Path to the playbook directory.",
    ),
) -> None:
    """Launch TUI and immediately open the Run modal for a ticket."""
    from .tui import run_tui

    run_tui(run_input=str(input), run_playbook=str(playbook))


# ──────────────────────────────────────────────────────────────────────────
#  channel adapters (ADR-0012)
# ──────────────────────────────────────────────────────────────────────────

channel_app = typer.Typer(
    name="channel",
    help="Channel adapters — external messaging surfaces (assist mode).",
    no_args_is_help=True,
)
app.add_typer(channel_app)


@channel_app.command("telegram")
def channel_telegram(
    chat_id: list[int] = typer.Option(  # noqa: B008
        ...,
        "--chat-id",
        help="Allowlisted Telegram chat id (repeatable). Messages from any other chat are dropped.",
    ),
    api_url: str = typer.Option(
        "http://127.0.0.1:8001", "--api-url", help="Base URL of the running OpsPilot API."
    ),
    poll_timeout: int = typer.Option(
        50, "--poll-timeout", help="getUpdates long-poll timeout in seconds."
    ),
) -> None:
    """Run the Telegram assist channel (long polling; see docs/adr/0012).

    Requires TELEGRAM_BOT_TOKEN in the environment and a running
    `opspilot serve`. The OpsPilot API token (if configured) is picked up
    from OPSPILOT_API_TOKEN / config.yaml automatically.
    """
    from .channels import TelegramChannel, TelegramConfig

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        _err.print(
            "[red]TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather "
            "and export the token (never pass it as a CLI argument).[/red]"
        )
        raise typer.Exit(code=1)

    cfg = TelegramConfig(
        bot_token=bot_token,
        allowed_chat_ids=frozenset(chat_id),
        api_url=api_url,
        api_token=load_config().api_token,
        poll_timeout_s=poll_timeout,
    )
    _console.print(
        f"Telegram channel starting — {len(cfg.allowed_chat_ids)} allowlisted chat(s), "
        f"api={api_url} (Ctrl+C to stop)"
    )
    try:
        TelegramChannel(cfg).run_forever()
    except KeyboardInterrupt:
        _console.print("\n[dim]channel stopped[/dim]")


# ──────────────────────────────────────────────────────────────────────────
#  source adapters (ADR-0013)
# ──────────────────────────────────────────────────────────────────────────

source_app = typer.Typer(
    name="source",
    help="Source adapters — pull Work items from an external system of record.",
    no_args_is_help=True,
)
app.add_typer(source_app)


@source_app.command("jsm")
def source_jsm(
    replay: Path | None = typer.Option(  # noqa: B008
        None,
        "--replay",
        exists=True,
        file_okay=False,
        help="Replay recorded JSM API responses from this fixtures directory (one pass, offline).",
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="JSM site base URL, e.g. https://yoursite.atlassian.net."
    ),
    email: str | None = typer.Option(
        None, "--email", help="Atlassian account email (basic-auth username for the API token)."
    ),
    jql: str | None = typer.Option(
        None,
        "--jql",
        help="Explicit intake scope, e.g. 'project = IT AND status = \"Open\"'. "
        "Only matching issues are ever fetched or run.",
    ),
    interval: int = typer.Option(60, "--interval", help="Poll interval in seconds (live mode)."),
    once: bool = typer.Option(
        False, "--once", help="Run a single intake pass and exit (cron-style)."
    ),
    out: Path = typer.Option(  # noqa: B008
        Path("intake_comments"),
        "--out",
        help="Directory where suggestion comments are written (replay mode only; "
        "live mode posts them to the JSM issue).",
    ),
    api_url: str = typer.Option(
        "http://127.0.0.1:8001", "--api-url", help="Base URL of the running OpsPilot API."
    ),
    state: Path = typer.Option(  # noqa: B008
        Path("intake_state.json"),
        "--state",
        help="Persistent intake state file (processed keys) — survives restarts.",
    ),
    playbook_id: str | None = typer.Option(
        None,
        "--playbook",
        help="Pin every intake run to this server-side playbook id "
        "(skips Classification; must be loaded by the server).",
    ),
    model_id: str | None = typer.Option(
        None,
        "--model",
        help="Model override for every intake run, e.g. "
        "anthropic/claude-haiku-4-5-20251001 (must be the playbook's "
        "primary or one of its extra_models).",
    ),
    rerun: list[str] = typer.Option(  # noqa: B008
        [],
        "--rerun",
        help="Forget this issue key so it runs again this pass (repeatable; "
        "the key must still match the intake scope).",
    ),
) -> None:
    """Run the JSM intake adapter (polling, outbound-only; see docs/adr/0013).

    Replay mode (--replay) runs one offline pass from fixtures. Live mode
    needs --base-url, --email, --jql and JSM_API_TOKEN in the environment.
    Requires a running `opspilot serve`; the OpsPilot API token (if
    configured) is picked up from OPSPILOT_API_TOKEN / config.yaml
    automatically.
    """
    from .channels import WeComNotifier
    from .intake import IntakeLoop, IntakeState, JsmTransport, OpsPilotRunClient, ReplayTransport

    client = OpsPilotRunClient(
        api_url=api_url,
        api_token=load_config().api_token,
        playbook_id=playbook_id,
        model_id=model_id,
    )
    wecom_url = os.environ.get("WECOM_WEBHOOK_URL")
    notifier = WeComNotifier(wecom_url) if wecom_url else None
    if notifier is not None:
        _console.print("WeCom notifications enabled (group-robot webhook)")
    intake_state = IntakeState(state)
    for key in rerun:
        if intake_state.forget(key):
            _console.print(f"rerun: {key} forgotten — runs again this pass")
        else:
            _console.print(f"[yellow]rerun: {key} was not in state — nothing to forget[/yellow]")

    if replay is not None:
        loop = IntakeLoop(
            ReplayTransport(replay, out), client, state=intake_state, notifier=notifier
        )
    else:
        missing = [
            name
            for name, value in (("--base-url", base_url), ("--email", email), ("--jql", jql))
            if not value
        ]
        if missing:
            _err.print(f"[red]Live mode needs {', '.join(missing)} (or use --replay).[/red]")
            raise typer.Exit(code=1)
        jsm_token = os.environ.get("JSM_API_TOKEN")
        if not jsm_token:
            _err.print(
                "[red]JSM_API_TOKEN is not set. Create an Atlassian API token and "
                "export it (never pass it as a CLI argument).[/red]"
            )
            raise typer.Exit(code=1)
        assert base_url and email and jql  # narrowed above
        transport = JsmTransport(base_url=base_url, email=email, api_token=jsm_token, jql=jql)
        loop = IntakeLoop(transport, client, state=intake_state, notifier=notifier)
        if not once:
            _console.print(f"JSM intake polling every {interval}s — scope: {jql} (Ctrl+C to stop)")
            try:
                loop.run_forever(interval)
            except KeyboardInterrupt:
                _console.print("\n[dim]source stopped[/dim]")
            return

    try:
        report = loop.run_once()
    except Exception as exc:  # noqa: BLE001 — single pass: report and exit non-zero
        _err.print(f"[red]intake pass failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    dest = str(out) if replay is not None else "JSM comments"
    _console.print(
        f"intake pass done — {len(report.commented)} commented, "
        f"{len(report.skipped)} skipped → {dest}"
    )
    for key, reason in report.skipped:
        _console.print(f"  [yellow]skip[/yellow] {key}: {reason}")


# ──────────────────────────────────────────────────────────────────────────
#  inventory (ADR-0017)
# ──────────────────────────────────────────────────────────────────────────

workingset_app = typer.Typer(
    name="workingset",
    help="Working set — the problem you are currently chasing (ADR-0032).",
    no_args_is_help=True,
)
app.add_typer(workingset_app)


def _working_sets() -> Any:
    from .consultation import WorkingSetStore

    return WorkingSetStore(init_sqlite(load_config().home / "kb" / "sqlite.db"))


@workingset_app.command("open")
def workingset_open(
    title: str = typer.Argument(..., help="What you are chasing."),
    scope: str = typer.Option("", "--scope", help="Site / environment it lives at."),
    asset: str = typer.Option("", "--asset", help="Asset it is about (ast_...)."),
) -> None:
    """Start chasing a problem. Any set already open is closed as a deliberate switch.

    The anchors given here are what lets a chat turn see *anchored* Memory —
    without them a turn sees the global constraints and nothing else.
    """
    ws = _working_sets().open(
        owner=_cli_actor(), title=title, scope=scope or None, asset_id=asset or None
    )
    where = ws.scope or ws.asset_id or "no anchor — global constraints only"
    _console.print(f"[green]{ws.id}[/green] open — {ws.title} · {where}")


@workingset_app.command("status")
def workingset_status() -> None:
    """Show the open Working set, and any closure not yet announced."""
    store = _working_sets()
    owner = _cli_actor()
    notice = store.take_announcement(owner)
    if notice:
        _console.print(f"[yellow]{notice}[/yellow]\n")
    current = store.current(owner)
    if current is None:
        _console.print("[dim]No working set open — chat turns see global Memory only.[/dim]")
        return
    where = current.scope or current.asset_id or "no anchor"
    _console.print(
        f"[bold]{current.id}[/bold] — {current.title}\n"
        f"anchor: {where} · last active {current.last_active_at[:19]}"
    )


@workingset_app.command("close")
def workingset_close() -> None:
    """Close the open Working set — the problem is done."""
    store = _working_sets()
    current = store.current(_cli_actor())
    if current is None:
        _console.print("[dim]Nothing open.[/dim]")
        return
    store.close(current.id)
    _console.print(f"[green]{current.id}[/green] closed — {current.title}")


@workingset_app.command("sweep")
def workingset_sweep(
    days: int = typer.Option(None, "--days", help="Override the idle window."),
) -> None:
    """Close every Working set idle past the window, for everyone.

    Unconditional by design: nobody returns to press close at the moment a
    problem is solved, and a set that never expires quietly injects the wrong
    context into every later conversation without ever raising an error.
    """
    from .consultation import IDLE_DAYS

    window = days if days is not None else IDLE_DAYS
    closed = _working_sets().sweep(idle_days=window)
    for ws in closed:
        _console.print(f"[yellow]{ws.id}[/yellow] closed ({ws.owner}) — {ws.title}")
    _console.print(f"[green]{len(closed)}[/green] working set(s) closed (idle > {window}d)")


consultation_app = typer.Typer(
    name="consultation",
    help="Consultation — the conversational surface (ADR-0032).",
    no_args_is_help=True,
)
app.add_typer(consultation_app)


def _consultations() -> Any:
    from .consultation import ConsultationStore

    return ConsultationStore(init_sqlite(load_config().home / "kb" / "sqlite.db"))


@consultation_app.command("list")
def consultation_list(
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """List Consultations.

    Over HTTP a Consultation is visible to its author and to admins. There is no
    auth context on the CLI, so this reads as an admin would — the same
    concession ``_cli_actor()`` makes: anyone who can run this can read the file.
    """
    from .consultation import RETENTION_DAYS

    rows = _consultations().list_for(name=_cli_actor(), role="admin", limit=limit)
    if not rows:
        _console.print("[green]No Consultations.[/green]")
        return
    table = Table(title=f"Consultations (swept after {RETENTION_DAYS}d idle unless pinned)")
    for col in ("ID", "Author", "Title", "Updated", "State"):
        table.add_column(col, overflow="fold")
    for c in rows:
        state = f"pinned ({c.pinned_reason})" if c.is_pinned else "live"
        if c.session_id:
            state += f" → {c.session_id}"
        table.add_row(c.id, c.author, c.title or "—", c.updated_at[:19], state)
    _console.print(table)


@consultation_app.command("show")
def consultation_show(
    consultation_id: str = typer.Argument(..., help="Consultation id (con_xxxxxxxx)."),
) -> None:
    """Print a Consultation's turns in order."""
    store = _consultations()
    con = store.get(consultation_id)
    if con is None:
        _err.print(f"[red]not found:[/red] {consultation_id}")
        raise typer.Exit(code=1)
    _console.print(f"[bold]{con.id}[/bold] — {con.title or '(untitled)'} · by {con.author}")
    for m in store.messages(con.id):
        who = "[cyan]you[/cyan]" if m.role == "user" else "[magenta]assistant[/magenta]"
        _console.print(f"\n[{m.seq}] {who}  [dim]{m.id}[/dim]\n{m.content}")


@consultation_app.command("purge")
def consultation_purge(
    days: int = typer.Option(None, "--days", help="Override the retention window."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would go, delete nothing."),
) -> None:
    """Sweep Consultations idle past the retention window.

    Pinned ones are never swept: something permanent cites them — a Session they
    escalated into, or a Memory entry admitted from them.
    """
    from .consultation import RETENTION_DAYS

    store = _consultations()
    window = days if days is not None else RETENTION_DAYS
    if dry_run:
        pinned = sum(
            1 for c in store.list_for(name=_cli_actor(), role="admin", limit=10_000) if c.is_pinned
        )
        _console.print(f"[dim]window {window}d · {pinned} pinned Consultation(s) are exempt[/dim]")
        return
    removed = store.purge(older_than_days=window)
    _console.print(f"[green]{len(removed)}[/green] Consultation(s) swept (window {window}d)")


memory_app = typer.Typer(
    name="memory",
    help="Memory — standing environment facts that have no table (ADR-0031).",
    no_args_is_help=True,
)
app.add_typer(memory_app)


@memory_app.command("add")
def memory_add(
    statement: str = typer.Argument(..., help="The fact, as one sentence."),
    reason: str = typer.Option(..., "--reason", "-m", help="Why it is worth recording."),
    scope: str = typer.Option("", "--scope", help="Site / environment / system it applies at."),
    asset: str = typer.Option("", "--asset", help="Asset this applies to (ast_...)."),
    review_after: str = typer.Option("", "--review-after", help="RFC3339 date to re-check it."),
) -> None:
    """Admit one Memory entry.

    Writing it yourself is the strongest form of admission: author and admitter
    are the same person, and the judgement rests on their own knowledge
    (ADR-0030). The actor is the OS user — never taken from an argument.
    """
    from .memory import AdmissionError, MemoryStore

    cfg = load_config()
    store = MemoryStore(init_sqlite(cfg.home / "kb" / "sqlite.db"))
    try:
        entry = store.admit(
            statement=statement,
            reason=reason,
            actor=_cli_actor(),
            asset_id=asset or None,
            scope=scope or None,
            review_after=review_after or None,
        )
    except AdmissionError as e:
        _err.print(f"[red]not admitted:[/red] {e}")
        raise typer.Exit(code=1) from e
    where = entry.scope or entry.asset_id or "everywhere"
    _console.print(f"[green]{entry.id}[/green] admitted by {entry.actor} — applies at {where}")


@memory_app.command("list")
def memory_list(
    scope: str = typer.Option("", "--scope", help="Only what applies at this scope."),
    asset: str = typer.Option("", "--asset", help="Only what applies to this Asset."),
    retired: bool = typer.Option(False, "--retired", help="Include superseded and archived."),
) -> None:
    """List Memory entries; with --scope/--asset, only what applies there."""
    from .memory import MemoryStore
    from .timeutil import now_rfc3339

    cfg = load_config()
    store = MemoryStore(init_sqlite(cfg.home / "kb" / "sqlite.db"))
    entries = (
        store.applicable(asset_id=asset or None, scope=scope or None)
        if (scope or asset)
        else store.list_entries(include_retired=retired)
    )
    if not entries:
        _console.print("[green]No Memory entries.[/green]")
        return
    now = now_rfc3339()
    table = Table(title="Memory")
    for col in ("ID", "Statement", "Applies at", "By", "State"):
        table.add_column(col, overflow="fold")
    for e in entries:
        state = "superseded" if e.superseded_at else "archived" if e.archived_at else "live"
        if e.is_live and e.review_overdue_at(now):
            state = "live [yellow](review overdue)[/yellow]"
        table.add_row(e.id, e.statement, e.scope or e.asset_id or "everywhere", e.actor, state)
    _console.print(table)


@memory_app.command("supersede")
def memory_supersede(
    entry_id: str = typer.Argument(..., help="The entry that no longer holds (mem_xxxxxxxx)."),
    statement: str = typer.Option(..., "--statement", "-s", help="What is true now."),
    reason: str = typer.Option(..., "--reason", "-m", help="Why it changed."),
) -> None:
    """Replace an entry by appending a new one; the old one is kept, marked superseded."""
    from .memory import AdmissionError, MemoryStore

    cfg = load_config()
    store = MemoryStore(init_sqlite(cfg.home / "kb" / "sqlite.db"))
    try:
        new = store.supersede(entry_id, statement=statement, reason=reason, actor=_cli_actor())
    except (AdmissionError, KeyError) as e:
        _err.print(f"[red]not superseded:[/red] {e}")
        raise typer.Exit(code=1) from e
    _console.print(f"[green]{new.id}[/green] supersedes {entry_id}")


@memory_app.command("scopes")
def memory_scopes() -> None:
    """List the scopes already in use — pick one before inventing another."""
    from .memory import MemoryStore

    cfg = load_config()
    store = MemoryStore(init_sqlite(cfg.home / "kb" / "sqlite.db"))
    scopes = store.scopes()
    _console.print("\n".join(scopes) if scopes else "[green]No scopes yet.[/green]")


inventory_app = typer.Typer(
    name="inventory",
    help="Asset inventory — CSV import/export (ADR-0017).",
    no_args_is_help=True,
)
app.add_typer(inventory_app)


@inventory_app.command("import")
def inventory_import(
    file: Path = typer.Argument(  # noqa: B008
        ..., exists=True, help="CSV file to import (spreadsheet migration path)."
    ),
) -> None:
    """Import Assets from a CSV file (one Asset per row; bad rows are skipped)."""
    from .inventory import InventoryStore, import_csv

    cfg = load_config()
    conn = init_sqlite(cfg.home / "kb" / "sqlite.db")
    store = InventoryStore(conn)
    report = import_csv(store, file, actor=_cli_actor())
    if report.unknown_columns:
        _console.print(
            f"[yellow]Unknown column(s) ignored: {', '.join(report.unknown_columns)}[/yellow]"
        )
    for row_number, reason in report.skipped:
        _console.print(f"  [yellow]skip[/yellow] row {row_number}: {reason}")
    _console.print(f"[green]{report.created}[/green] asset(s) imported from {file}")


@inventory_app.command("export")
def inventory_export(
    file: Path = typer.Argument(..., help="Destination CSV file."),  # noqa: B008
) -> None:
    """Export every Asset to a CSV file."""
    from .inventory import InventoryStore, export_csv

    cfg = load_config()
    conn = init_sqlite(cfg.home / "kb" / "sqlite.db")
    store = InventoryStore(conn)
    count = export_csv(store, file)
    _console.print(f"[green]{count}[/green] asset(s) exported to {file}")


@inventory_app.command("warranty-check")
def inventory_warranty_check(
    days: int = typer.Option(
        30, "--days", help="Flag warranties ending within this many days (or already ended)."
    ),
) -> None:
    """List expiring warranties; push a WeCom summary when WECOM_WEBHOOK_URL is set.

    Cron-friendly: exits 0 either way; scheduling stays outside the server
    (ADR-0012 posture — no resident scheduler).
    """
    from .inventory import InventoryStore

    cfg = load_config()
    conn = init_sqlite(cfg.home / "kb" / "sqlite.db")
    store = InventoryStore(conn)
    rows = store.expiring_warranties(days)
    if not rows:
        _console.print(f"[green]No warranties ending within {days} day(s).[/green]")
        return
    for r in rows:
        _console.print(
            f"  [yellow]{r['warranty_until'][:10]}[/yellow] {r['asset_tag'] or r['asset_id']} "
            f"— {r['brand_model'] or r['category'] or '?'} ({r['assignee'] or 'unassigned'})"
        )
    _console.print(f"[yellow]{len(rows)}[/yellow] warrant(ies) ending within {days} day(s)")
    wecom_url = os.environ.get("WECOM_WEBHOOK_URL")
    if wecom_url:
        from .channels import WeComNotifier

        lines = [
            f"- {r['warranty_until'][:10]} — {r['asset_tag'] or r['asset_id']} "
            f"{r['brand_model'] or r['category']} ({r['assignee'] or 'unassigned'})"
            for r in rows
        ]
        WeComNotifier(wecom_url).notify(
            f"Warranty check: {len(rows)} ending within {days}d", "\n".join(lines)
        )
        _console.print("WeCom summary pushed (group-robot webhook)")


# ──────────────────────────────────────────────────────────────────────────
#  serve (PR-32)
# ──────────────────────────────────────────────────────────────────────────


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _remote_binding_error(host: str, token: str | None) -> str | None:
    """Fail-closed guard (ADR-0011): non-loopback binds require an API token.

    Mirrors the sandbox L3 philosophy — refuse to start rather than silently
    expose an unauthenticated API beyond localhost.
    """
    if host in _LOOPBACK_HOSTS or token:
        return None
    return (
        f"Refusing to bind on {host!r} without an API token: every safety "
        "property assumes a trusted local caller (see SECURITY.md). Set "
        "OPSPILOT_API_TOKEN (or api_token in ~/.opspilot/config.yaml) and "
        "retry, or bind to 127.0.0.1."
    )


def _kb_open_error(cfg: Config) -> str | None:
    """Preflight the KB open that the API server does at startup.

    The store refuses to open a dataset built by a different embedder (or at a
    different width), but inside uvicorn's lifespan that surfaces as a
    traceback ending in "Application startup failed". Doing it here first
    turns a configuration problem back into a one-line refusal, like the API
    token guard above.
    """
    from .embedding import EMBED_DIM, resolve_embedding

    kb_path = cfg.home / "kb" / "lancedb"
    if not kb_path.exists():
        return None  # nothing to conflict with yet

    _embed_fn, status = resolve_embedding(cfg)
    try:
        LanceStore.open_or_create(
            kb_path,
            dim=EMBED_DIM,
            embedding_model=status.model,
            allow_model_mismatch=os.environ.get("OPSPILOT_ALLOW_EMBED_MISMATCH") == "1",
        )
    except ValueError as exc:  # the store's own refusals; message is self-explanatory
        return str(exc)
    return None


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Bind host."),
    port: int = typer.Option(8001, "--port", "-p", help="Bind port."),
    workers: int = typer.Option(1, "--workers", "-w", help="Uvicorn worker count."),
    reload: bool = typer.Option(False, "--reload", help="Hot-reload (dev only)."),
    json_logs: bool = typer.Option(False, "--json-logs", help="Enable JSON structured logging."),
    with_ui: bool = typer.Option(
        False, "--with-ui", help="Also start the Svelte frontend (pnpm dev)."
    ),
    ui_port: int = typer.Option(
        5173, "--ui-port", help="Frontend dev server port (used with --with-ui)."
    ),
    ssl_certfile: Path | None = typer.Option(  # noqa: B008
        None, "--ssl-certfile", help="TLS certificate (PEM); prefer a reverse proxy."
    ),
    ssl_keyfile: Path | None = typer.Option(  # noqa: B008
        None, "--ssl-keyfile", help="TLS private key (PEM); prefer a reverse proxy."
    ),
) -> None:
    """Start the OpsPilot FastAPI server with uvicorn.

    Use --with-ui to start the Svelte frontend alongside the API server.
    Both processes are stopped together on Ctrl+C.

    Binding beyond loopback requires an API token (OPSPILOT_API_TOKEN);
    see docs/deployment.md for the remote-access setup.
    """
    import atexit
    import os
    import subprocess

    import uvicorn

    from .api.middleware import configure_json_logging

    cfg = load_config()
    binding_error = _remote_binding_error(host, cfg.api_token)
    if binding_error:
        _err.print(f"[red]{binding_error}[/red]")
        raise typer.Exit(code=1)

    kb_error = _kb_open_error(cfg)
    if kb_error:
        _err.print(f"[red]{kb_error}[/red]")
        raise typer.Exit(code=1)

    if json_logs:
        configure_json_logging()
        _console.print("[dim]JSON logging enabled[/dim]")

    frontend_proc: subprocess.Popen[bytes] | None = None
    if with_ui:
        web_dir = REPO_ROOT / "web"
        if not (web_dir / "package.json").exists():
            _err.print(f"[red]web/ not found at {web_dir}[/red]")
            raise typer.Exit(code=1)
        _console.print(f"Starting Svelte frontend on http://localhost:{ui_port}")
        # Tell Vite which backend port to proxy /api → so a non-default --port works.
        frontend_env = {**os.environ, "OPSPILOT_API_PORT": str(port)}
        frontend_proc = subprocess.Popen(
            ["pnpm", "dev", "--port", str(ui_port)],
            cwd=web_dir,
            env=frontend_env,
        )

        def _stop_frontend() -> None:
            if frontend_proc and frontend_proc.poll() is None:
                frontend_proc.terminate()
                try:
                    frontend_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    frontend_proc.kill()

        atexit.register(_stop_frontend)

    scheme = "https" if ssl_certfile else "http"
    _console.print(f"Starting OpsPilot API on {scheme}://{host}:{port}")
    uvicorn.run(
        "opspilot.api.app:app",
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        ssl_certfile=str(ssl_certfile) if ssl_certfile else None,
        ssl_keyfile=str(ssl_keyfile) if ssl_keyfile else None,
        log_config=None if json_logs else uvicorn.config.LOGGING_CONFIG,
    )


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
