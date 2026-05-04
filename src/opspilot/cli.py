"""OpsPilot CLI entry point.

* ``opspilot init``         — create ``~/.opspilot/`` subtree
* ``opspilot validate``     — JSON-schema-validate one file or a directory
* ``opspilot schemas``      — list registered schemas (debug)
* ``opspilot ingest``       — run KB ingestion pipeline (PR-5)
* ``opspilot kb-search``    — hybrid retrieval over KB (PR-5)
* ``opspilot run``          — run a playbook end-to-end (PR-7)
* ``opspilot harness run``  — run a single fixture through harness (PR-8)
* ``opspilot harness golden`` — run the Stage 1 golden test (PR-8)
* ``opspilot wiki ingest``  — generate wiki page from KB document (PR-19)
* ``opspilot tui``          — launch the terminal UI (PR-20)
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import ensure_home, load_config
from .errors import OpsPilotError, SchemaError
from .harness import load_fixture, load_golden, run_harness
from .harness.reporter import render_result_table
from .memory.ingestion import IngestConfig
from .memory.ingestion import ingest as run_ingest
from .memory.kb_loader import load_kb_fixture
from .memory.lance_store import LanceStore
from .memory.retrieval import kb_search
from .memory.sqlite_store import SqliteStore
from .memory.storage_init import init_sqlite
from .orchestrator import RunRequest, load_playbook, run_ticket_summary
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
from .wiki.ingest import WikiIngestConfig
from .wiki.ingest import ingest as run_wiki_ingest

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
        table.add_row("ticket_ref", str(result.summary.get("ticket_ref", "?")))
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


harness_app = typer.Typer(
    name="harness",
    help="Evaluation harness: run fixtures, compute scores, emit results.jsonl.",
    no_args_is_help=True,
)
app.add_typer(harness_app)


REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_FIXTURE_PATH = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "harness" / "fixture.json"
GOLDEN_GOLDEN_PATH = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "harness" / "golden.json"
GOLDEN_PLAYBOOK_DIR = REPO_ROOT / "playbooks" / "pb_ticket_summary_zh"


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
) -> int:
    """Shared entrypoint for both ``run`` and ``golden`` subcommands.

    Returns the desired CLI exit code.
    """
    cfg = load_config()
    fixture = load_fixture(fixture_path)
    golden = load_golden(golden_path)
    playbook = load_playbook(playbook_dir)

    sqlite, lance = _open_kb_stores(
        home=cfg.home,
        embedding_dim=embedding_dim,
        embedding_model=embedding_model,
    )
    redactor = Redactor.from_yaml()
    provider = make_provider("ollama-local")
    sm = __import__("opspilot.session", fromlist=["SessionManager"]).SessionManager(home=cfg.home)

    def embed_fn(text: str) -> list[float]:
        return provider.embed([text], model=embed_model_short)[0]

    result = run_harness(
        fixture=fixture,
        golden=golden,
        playbook=playbook,
        session_manager=sm,
        provider=provider,
        redactor=redactor,
        embed_fn=embed_fn,
        sqlite_store=sqlite,
        lance_store=lance,
        owner=owner,
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
