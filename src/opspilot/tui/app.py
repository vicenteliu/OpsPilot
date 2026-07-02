"""OpsPilot TUI — Claude Code-style REPL shell.

Layout:
  ┌─ Header ──────────────────────────────────────────────────┐
  │ RichLog — scrollable conversation output (1fr)            │
  ├───────────────────────────────────────────────────────────┤
  │ opspilot> [Input]                                         │
  └─ Footer ──────────────────────────────────────────────────┘

All interaction happens through slash commands in the input line,
mirroring the Claude Code operational model:
  /help           — list commands
  /run            — run ticket through orchestrator
  /kb search      — search knowledge base
  /kb list        — list KB documents
  /kb stats       — KB aggregate counts
  /sessions       — list recent sessions
  /session <id>   — inspect a single session
  /wiki list      — list wiki pages
  /wiki show      — show wiki page body
  /wiki lint      — run wiki linter
  /harness        — run harness fixture
  /providers      — show provider config
  /config         — show full config
  /lineage        — show skill version lineage
  /clear          — clear the output pane
  Ctrl+C / /quit  — exit
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Input, Label, RichLog

_DEFAULT_PLAYBOOK = "playbooks/pb_ticket_summary_en"
_EMBED_MODEL = "nomic-embed-text-v2-moe"
_EMBED_MODEL_REF = "ollama-local/nomic-embed-text-v2-moe@2026-04"

_HELP = """\
[bold cyan]OpsPilot Commands[/bold cyan]

  [bold]/run[/bold] <ticket.json> [--playbook <dir>]            Run ticket through orchestrator
  [bold]/kb search[/bold] <query> [--top-k N]                   Search knowledge base
  [bold]/kb list[/bold]                                          List KB documents
  [bold]/kb stats[/bold]                                         KB aggregate stats
  [bold]/sessions[/bold] [--limit N]                            List recent sessions (default 20)
  [bold]/session[/bold] <id>                                     Inspect a session
  [bold]/wiki list[/bold]                                        List wiki pages
  [bold]/wiki show[/bold] <slug>                                 Show wiki page body
  [bold]/wiki lint[/bold]                                        Run wiki linter
  [bold]/harness[/bold] <fixture.json> <golden.json> [--playbook <dir>]  Run harness
  [bold]/providers[/bold]                                        Show provider configuration
  [bold]/config[/bold]                                           Show current configuration
  [bold]/lineage[/bold]                                          Show skill version lineage
  [bold]/clear[/bold]                                            Clear output
  [bold]/quit[/bold] or Ctrl+C                                   Exit OpsPilot
"""


class OpsPilotApp(App[None]):
    """OpsPilot terminal workbench — REPL chat shell."""

    TITLE = "OpsPilot"

    CSS = """
    #output {
        height: 1fr;
        scrollbar-size: 1 1;
        padding: 0 1;
    }
    #input-area {
        height: 3;
        border-top: solid $primary-darken-2;
        background: $surface;
        layout: horizontal;
    }
    #prompt-label {
        width: 14;
        height: 3;
        content-align: left middle;
        color: $success;
        padding: 0 1;
    }
    #cmd-input {
        width: 1fr;
        height: 3;
        border: none;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear_output", "Clear"),
    ]

    def __init__(self, run_input: str = "", run_playbook: str = "") -> None:
        super().__init__()
        self._run_input = run_input
        self._run_playbook = run_playbook or _DEFAULT_PLAYBOOK

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="output", markup=True, highlight=False, wrap=True)
        with Horizontal(id="input-area"):
            yield Label("opspilot> ", id="prompt-label")
            yield Input(placeholder="/help for commands", id="cmd-input")
        yield Footer()

    def on_mount(self) -> None:
        self._write("[bold cyan]OpsPilot[/bold cyan] — AI-powered SRE workbench")
        self._write("Type [bold]/help[/bold] to see available commands.\n")
        self.query_one("#cmd-input", Input).focus()
        if self._run_input:
            self.set_timer(
                0.3, lambda: self._cmd_run(self._run_input, self._run_playbook, "tui@opspilot")
            )

    # ── Output helpers ────────────────────────────────────────────────────────

    def _write(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one(RichLog).write(msg)

    def _wt(self, msg: str) -> None:
        """Thread-safe write."""
        self.call_from_thread(self._write, msg)

    # ── Input handling ────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        if not raw:
            return
        self._write(f"[bold green]›[/bold green] {raw}")
        self._dispatch(raw)

    def _dispatch(self, raw: str) -> None:  # noqa: C901 PLR0912
        if not raw.startswith("/"):
            self._write("[dim]Commands start with /  Try /help[/dim]\n")
            return

        tokens = raw[1:].split()
        if not tokens:
            return
        cmd = tokens[0].lower()
        rest = tokens[1:]

        if cmd in ("help", "h", "?"):
            self._write(_HELP)

        elif cmd == "clear":
            self.action_clear_output()

        elif cmd in ("quit", "exit", "q"):
            self.exit()

        elif cmd == "run":
            ticket = next((r for r in rest if not r.startswith("-")), "")
            pb = self._extract_flag(rest, "--playbook") or self._run_playbook
            if not ticket:
                self._write("[red]Usage: /run <ticket.json> [--playbook <dir>][/red]")
                return
            self._cmd_run(ticket, pb, "tui@opspilot")

        elif cmd == "kb":
            sub = rest[0].lower() if rest else ""
            if sub == "search":
                rest2 = rest[1:]
                top_k = int(self._extract_flag(rest2, "--top-k") or "5")
                query = " ".join(r for r in rest2 if not r.startswith("-"))
                if not query:
                    self._write("[red]Usage: /kb search <query> [--top-k N][/red]")
                    return
                self._cmd_kb_search(query, top_k)
            elif sub == "list":
                self._cmd_kb_list()
            elif sub == "stats":
                self._cmd_kb_stats()
            else:
                self._write("[dim]kb sub-commands: search, list, stats[/dim]")

        elif cmd == "sessions":
            limit = int(self._extract_flag(rest, "--limit") or "20")
            self._cmd_sessions(limit)

        elif cmd == "session":
            sid = rest[0] if rest else ""
            if not sid:
                self._write("[red]Usage: /session <session-id>[/red]")
                return
            self._cmd_session_show(sid)

        elif cmd == "wiki":
            sub = rest[0].lower() if rest else ""
            if sub == "list":
                self._cmd_wiki_list()
            elif sub == "show":
                slug = " ".join(rest[1:]) if len(rest) > 1 else ""
                if not slug:
                    self._write("[red]Usage: /wiki show <slug>[/red]")
                    return
                self._cmd_wiki_show(slug)
            elif sub == "lint":
                self._cmd_wiki_lint()
            else:
                self._write("[dim]wiki sub-commands: list, show, lint[/dim]")

        elif cmd == "harness":
            positional = [r for r in rest if not r.startswith("-")]
            fixture = positional[0] if len(positional) > 0 else ""
            golden = positional[1] if len(positional) > 1 else ""
            pb = self._extract_flag(rest, "--playbook") or self._run_playbook
            if not fixture or not golden:
                self._write(
                    "[red]Usage: /harness <fixture.json> <golden.json> [--playbook <dir>][/red]"
                )
                return
            self._cmd_harness(fixture, golden, pb)

        elif cmd == "providers":
            self._cmd_providers()

        elif cmd == "config":
            self._cmd_config()

        elif cmd == "lineage":
            self._cmd_lineage()

        else:
            self._write(f"[red]Unknown command: /{cmd}[/red]  Try /help")

    @staticmethod
    def _extract_flag(tokens: list[str], flag: str) -> str | None:
        if flag in tokens:
            idx = tokens.index(flag)
            if idx + 1 < len(tokens):
                return tokens[idx + 1]
        return None

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_clear_output(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one(RichLog).clear()

    # ── /run ─────────────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_run(self, ticket: str, playbook_dir: str, owner: str) -> None:
        w = self._wt
        try:
            from ..config import load_config
            from ..memory.lance_store import LanceStore
            from ..memory.sqlite_store import SqliteStore
            from ..memory.storage_init import init_sqlite
            from ..orchestrator import RunRequest, load_playbook, run_ticket_summary
            from ..providers import make_provider
            from ..redaction import Redactor
            from ..session import SessionManager

            w("[dim]› loading config…[/dim]")
            cfg = load_config()

            pb_path = Path(playbook_dir)
            if not pb_path.is_absolute():
                pb_path = Path.cwd() / pb_path

            w(f"[dim]› loading playbook {pb_path.name}…[/dim]")
            pb = load_playbook(pb_path)

            w("[dim]› opening KB stores…[/dim]")
            kb_dir = cfg.home / "kb"
            kb_dir.mkdir(parents=True, exist_ok=True)
            sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
            lance = LanceStore.open_or_create(
                kb_dir / "lancedb", dim=768, embedding_model=_EMBED_MODEL_REF
            )
            embed_provider = make_provider("ollama-local")
            primary_provider = make_provider(pb.model.provider_id, kind=pb.model.kind)

            def embed_fn(text: str) -> list[float]:
                return embed_provider.embed([text], model=_EMBED_MODEL)[0]

            w("[dim]› running orchestrator…[/dim]")
            result = run_ticket_summary(
                RunRequest(playbook=pb, input_path=Path(ticket), owner=owner),
                session_manager=SessionManager(home=cfg.home),
                provider=primary_provider,
                redactor=Redactor.from_yaml(),
                embed_fn=embed_fn,
                sqlite_store=sqlite,
                lance_store=lance,
            )

            if result.error:
                w(f"[red]✗ {result.error}[/red]\n")
                return

            s = result.summary or {}
            w(f"\n[bold green]✓ Done[/bold green]  session [cyan]{result.session_id}[/cyan]")
            w(f"  Work item: {s.get('work_item_ref', '—')} ({s.get('work_item_type', '—')})")
            w(f"  Severity: {s.get('severity_suggested', '—')}")
            w(f"  Summary:  {s.get('summary', '—')}")
            symptoms = s.get("symptoms") or []
            if symptoms:
                w("  Symptoms:")
                for sym in symptoms:
                    w(f"    • {sym}")
            tasks = s.get("tasks") or []
            if tasks:
                w("  Tasks:")
                for i, task in enumerate(tasks, 1):
                    w(f"    {i}. [{task.get('tier', '?')}] {task.get('action', '?')}")
                    rat = task.get("rationale", "")
                    if rat:
                        w(f"       [dim]{rat}[/dim]")
            usage = result.usage
            if usage:
                w(
                    f"\n[dim]tokens in={usage.input_tokens} out={usage.output_tokens}  cost=${usage.cost_usd:.4f}[/dim]"
                )
            w("")

        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /kb search ────────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_kb_search(self, query: str, top_k: int) -> None:
        w = self._wt
        w(f"[dim]› kb_search q={query!r} top_k={top_k}[/dim]")
        try:
            from ..config import load_config
            from ..memory.lance_store import LanceStore
            from ..memory.retrieval import kb_search
            from ..memory.sqlite_store import SqliteStore
            from ..memory.storage_init import init_sqlite
            from ..providers import make_provider

            cfg = load_config()
            kb_dir = cfg.home / "kb"
            if not (kb_dir / "sqlite.db").exists():
                w("[yellow]KB not initialised yet.[/yellow]\n")
                return

            sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
            lance = LanceStore.open_or_create(
                kb_dir / "lancedb", dim=768, embedding_model=_EMBED_MODEL_REF
            )
            provider = make_provider("ollama-local")

            def embed_fn(text: str) -> list[float]:
                return provider.embed([text], model=_EMBED_MODEL)[0]

            hits = kb_search(query, sqlite=sqlite, lance=lance, embed_fn=embed_fn, top_k=top_k)

            if not hits:
                w("[yellow]No results found.[/yellow]\n")
                return

            w(f"\n[bold cyan]KB Search: {query!r}[/bold cyan] — {len(hits)} result(s)\n")
            for i, hit in enumerate(hits, 1):
                preview = (hit.content or "").replace("\n", " ")[:180]
                w(
                    f"[bold]{i}.[/bold] [cyan]{hit.chunk_id}[/cyan]  score=[yellow]{hit.score:.3f}[/yellow]"
                )
                w(f"   {preview}[dim]…[/dim]")
            w("")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /kb list ──────────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_kb_list(self) -> None:
        w = self._wt
        w("[dim]› listing KB documents…[/dim]")
        try:
            import sqlite3

            from ..config import load_config

            cfg = load_config()
            db_path = cfg.home / "kb" / "sqlite.db"
            if not db_path.exists():
                w("[yellow]No KB database found.[/yellow]\n")
                return

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, title, language, chunk_count, namespace, ingested_at "
                "FROM kb_documents ORDER BY ingested_at DESC"
            ).fetchall()
            conn.close()

            if not rows:
                w("[yellow]No documents ingested yet.[/yellow]\n")
                return

            w(f"\n[bold cyan]KB Documents[/bold cyan] — {len(rows)} doc(s)\n")
            for r in rows:
                w(
                    f"  [cyan]{r['id']}[/cyan]  {(r['title'] or '')[:40]}  "
                    f"[dim]{r['chunk_count']} chunks · {r['namespace'] or '—'}[/dim]"
                )
            w("")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /kb stats ─────────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_kb_stats(self) -> None:
        w = self._wt
        try:
            from ..config import load_config
            from ..memory.sqlite_store import SqliteStore
            from ..memory.storage_init import init_sqlite

            cfg = load_config()
            db_path = cfg.home / "kb" / "sqlite.db"
            if not db_path.exists():
                w("[yellow]No KB database found.[/yellow]\n")
                return

            stats = SqliteStore(init_sqlite(db_path)).kb_stats()
            w("\n[bold cyan]KB Stats[/bold cyan]")
            w(f"  Documents:   [yellow]{stats['docs_total']}[/yellow]")
            w(f"  Chunks:      [yellow]{stats['chunks_total']}[/yellow]")
            w(f"  Conflicts:   [yellow]{stats['open_conflicts']}[/yellow] open")
            w(f"  Corrections: [yellow]{stats['corrections_total']}[/yellow]\n")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /sessions ─────────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_sessions(self, limit: int) -> None:
        w = self._wt
        w("[dim]› loading sessions…[/dim]")
        try:
            from ..config import load_config
            from ..session import SessionManager

            cfg = load_config()
            sm = SessionManager(home=cfg.home)
            all_ids = sm.list()
            ids = list(reversed(all_ids))[:limit]

            if not ids:
                w("[yellow]No sessions yet.[/yellow]\n")
                return

            w(f"\n[bold cyan]Sessions[/bold cyan] — {len(all_ids)} total, showing {len(ids)}\n")
            for sid in ids:
                try:
                    s = sm.load(sid)
                    color = "green" if s.status == "archived" else "yellow"
                    w(
                        f"  [{color}]{s.status:8}[/{color}]  [cyan]{sid[:32]}[/cyan]  {s.created_at[:19]}"
                    )
                except Exception:  # noqa: BLE001
                    w(f"  [dim]{sid}[/dim]")
            w("")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /session <id> ─────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_session_show(self, session_id: str) -> None:
        w = self._wt
        try:
            from ..config import load_config
            from ..session import SessionManager

            cfg = load_config()
            sm = SessionManager(home=cfg.home)
            s = sm.load(session_id)

            color = "green" if s.status == "archived" else "yellow"
            w(f"\n[bold cyan]Session: {session_id}[/bold cyan]")
            w(f"  Status:  [{color}]{s.status}[/{color}]")
            w(f"  Created: {s.created_at}")
            w(f"  Owner:   {s.owner}")
            w(f"  Model:   {s.model.provider_id}/{s.model.name}")
            w("")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /wiki list ────────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_wiki_list(self) -> None:
        w = self._wt
        w("[dim]› listing wiki pages…[/dim]")
        try:
            from ..config import load_config
            from ..wiki.page import read_page

            cfg = load_config()
            pages_dir = cfg.home / "wiki" / "pages"
            if not pages_dir.is_dir():
                w("[yellow]No wiki pages found.[/yellow]\n")
                return

            pages = []
            for md in sorted(pages_dir.rglob("*.md")):
                with contextlib.suppress(Exception):
                    pages.append(read_page(md))

            if not pages:
                w("[yellow]No wiki pages found.[/yellow]\n")
                return

            w(f"\n[bold cyan]Wiki Pages[/bold cyan] — {len(pages)} page(s)\n")
            for p in pages:
                color = "green" if p.lifecycle_state == "live" else "yellow"
                w(f"  [{color}]{p.lifecycle_state:8}[/{color}]  [cyan]{p.slug}[/cyan]  {p.title}")
            w("")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /wiki show <slug> ─────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_wiki_show(self, slug: str) -> None:
        w = self._wt
        try:
            from ..config import load_config
            from ..wiki.page import read_page

            cfg = load_config()
            pages_dir = cfg.home / "wiki" / "pages"
            md_file = pages_dir / f"{slug}.md"
            if not md_file.is_file():
                found = list(pages_dir.rglob(f"{slug}.md"))
                if not found:
                    w(f"[red]Page not found: {slug!r}[/red]\n")
                    return
                md_file = found[0]

            page = read_page(md_file)
            color = "green" if page.lifecycle_state == "live" else "yellow"
            w(f"\n[bold cyan]{page.title}[/bold cyan]  [{color}]{page.lifecycle_state}[/{color}]")
            w(f"[dim]slug: {page.slug}  lang: {page.language}  tags: {', '.join(page.tags)}[/dim]")
            w(f"\n{page.summary}\n")
            w("─" * 60)
            body = page.body or ""
            if len(body) > 2000:
                w(body[:2000])
                w(f"\n[dim]… ({len(body)} chars total, truncated)[/dim]")
            else:
                w(body)
            w("")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /wiki lint ────────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_wiki_lint(self) -> None:
        w = self._wt
        w("[dim]› running wiki linter…[/dim]")
        try:
            from ..config import load_config
            from ..wiki.lint import lint_wiki

            cfg = load_config()
            issues = lint_wiki(cfg.home / "wiki")

            if not issues:
                w("[green]✓ No lint issues.[/green]\n")
                return

            w(f"\n[bold cyan]Wiki Lint[/bold cyan] — {len(issues)} issue(s)\n")
            for issue in issues:
                color = "red" if issue.severity == "error" else "yellow"
                w(
                    f"  [{color}]{issue.severity:8}[/{color}]  [cyan]{issue.page_slug}[/cyan]  {issue.summary}"
                )
            w("")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /harness ──────────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_harness(self, fixture_path: str, golden_path: str, playbook_dir: str) -> None:
        w = self._wt
        w(f"[dim]› harness fixture={fixture_path}[/dim]")
        try:
            from ..config import load_config
            from ..harness import load_fixture, load_golden, run_harness
            from ..memory.lance_store import LanceStore
            from ..memory.sqlite_store import SqliteStore
            from ..memory.storage_init import init_sqlite
            from ..orchestrator import load_playbook
            from ..providers import make_provider
            from ..redaction import Redactor
            from ..session import SessionManager

            cfg = load_config()

            pb_path = Path(playbook_dir)
            if not pb_path.is_absolute():
                pb_path = Path.cwd() / pb_path

            fixture = load_fixture(Path(fixture_path))
            golden = load_golden(Path(golden_path))
            playbook = load_playbook(pb_path)

            kb_dir = cfg.home / "kb"
            kb_dir.mkdir(parents=True, exist_ok=True)
            sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
            lance = LanceStore.open_or_create(
                kb_dir / "lancedb", dim=768, embedding_model=_EMBED_MODEL_REF
            )
            embed_provider = make_provider("ollama-local")
            chat_provider = make_provider(playbook.model.provider_id, kind=playbook.model.kind)

            def embed_fn(text: str) -> list[float]:
                return embed_provider.embed([text], model=_EMBED_MODEL)[0]

            result = run_harness(
                fixture=fixture,
                golden=golden,
                playbook=playbook,
                session_manager=SessionManager(home=cfg.home),
                provider=chat_provider,
                redactor=Redactor.from_yaml(),
                embed_fn=embed_fn,
                sqlite_store=sqlite,
                lance_store=lance,
            )

            if result.passed:
                w(f"[green]✓ PASS[/green]  score={result.weighted_score:.3f}  {fixture_path}\n")
            else:
                w(f"[red]✗ FAIL[/red]  score={result.weighted_score:.3f}  {fixture_path}")
                for ev in result.evaluators:
                    if not ev.passed:
                        detail = str(ev.details) if ev.details else "failed"
                        w(f"  [red]•[/red] [{ev.type}] {detail}")
                w("")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /providers ────────────────────────────────────────────────────────────

    def _cmd_providers(self) -> None:
        try:
            from ..config import load_config

            cfg = load_config()
            self._write("\n[bold cyan]Providers[/bold cyan]")
            self._write(f"  ollama_base_url:  [yellow]{cfg.ollama_base_url}[/yellow]")
            self._write(f"  embed_model:      [yellow]{cfg.embed_model}[/yellow]")
            self._write(
                f"  anthropic_key:    "
                f"{'[green]set[/green]' if cfg.anthropic_api_key else '[dim]not set[/dim]'}"
            )
            self._write("")
        except Exception as exc:  # noqa: BLE001
            self._write(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /config ───────────────────────────────────────────────────────────────

    def _cmd_config(self) -> None:
        try:
            from ..config import load_config

            cfg = load_config()
            self._write("\n[bold cyan]Configuration[/bold cyan]")
            self._write(f"  home:            [yellow]{cfg.home}[/yellow]")
            self._write(f"  ollama_base_url: [yellow]{cfg.ollama_base_url}[/yellow]")
            self._write(f"  embed_model:     [yellow]{cfg.embed_model}[/yellow]")
            self._write(
                f"  anthropic_key:   {'[green]set[/green]' if cfg.anthropic_api_key else '[dim]not set[/dim]'}"
            )
            self._write(f"  log_level:       [yellow]{cfg.log_level}[/yellow]")
            pb_dir = cfg.playbooks_dir or "(uses ./playbooks)"
            self._write(f"  playbooks_dir:   [yellow]{pb_dir}[/yellow]")
            self._write("")
        except Exception as exc:  # noqa: BLE001
            self._write(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")

    # ── /lineage ──────────────────────────────────────────────────────────────

    @work(thread=True)
    def _cmd_lineage(self) -> None:
        w = self._wt
        w("[dim]› loading lineage…[/dim]")
        try:
            import yaml

            from ..config import load_config

            cfg = load_config()
            lineage_dir = cfg.home / "skills" / "lineage"

            if not lineage_dir.is_dir():
                w("[yellow]No lineage data found.[/yellow]\n")
                return

            files = sorted(lineage_dir.glob("*.yaml"))
            if not files:
                w("[yellow]No lineage files found.[/yellow]\n")
                return

            w("\n[bold cyan]Skill Lineage[/bold cyan]\n")
            for yaml_file in files:
                skill_name = yaml_file.stem
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
                versions = data.get("versions", [])
                w(f"[bold]{skill_name}[/bold] ({len(versions)} versions)")
                for ver in reversed(versions[-5:]):
                    rolled = " [dim]⟲ rolled back[/dim]" if ver.get("rolled_back") else ""
                    promoted_at = (ver.get("promoted_at") or "")[:10]
                    summary = (ver.get("summary") or "")[:70]
                    w(
                        f"  [cyan]v{ver.get('version', '?')}[/cyan]  {promoted_at}  {summary}{rolled}"
                    )
                w("")
        except Exception as exc:  # noqa: BLE001
            w(f"[red]✗ {type(exc).__name__}: {exc}[/red]\n")


def run_tui(*, run_input: str = "", run_playbook: str = "") -> None:
    """Launch the OpsPilot TUI."""
    OpsPilotApp(run_input=run_input, run_playbook=run_playbook).run()
