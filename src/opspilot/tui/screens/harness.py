"""Harness screen — recent eval results + run trigger (PR-21)."""

from __future__ import annotations

import json
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, Input, Label, Static

_MODE_FIXTURE = "fixture"
_MODE_GOLDEN = "golden"
_MODE_PLAYBOOK = "playbook"


class HarnessScreen(Widget):
    DEFAULT_CSS = """
    HarnessScreen { height: 1fr; padding: 1; }
    DataTable { height: 1fr; }
    #harness-input-row { height: 3; }
    HarnessScreen.input-hidden #harness-input-row { display: none; }
    """

    BINDINGS = [
        Binding("r", "start_run", "Run harness", show=True),
        Binding("g", "run_golden", "Golden test", show=True),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pending_mode = ""
        self._fixture_path = ""
        self._golden_path = ""

    def compose(self) -> ComposeResult:
        yield Label("[b]Harness — Eval Results[/b] — [dim]R: run  G: golden test[/dim]")
        yield Static(id="harness-input-row")
        yield DataTable(id="harness-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.add_class("input-hidden")
        dt = self.query_one(DataTable)
        dt.add_columns("Fixture", "Playbook", "Score", "Pass", "Run at")
        self.load_results()

    # ── input helpers ──────────────────────────────────────────────────────

    def _show_input(self, placeholder: str, mode: str) -> None:
        self._pending_mode = mode
        self.remove_class("input-hidden")
        bar = self.query_one("#harness-input-row", Static)
        bar.remove_children()
        inp = Input(placeholder=placeholder, id="harness-cmd-input")
        bar.mount(inp)
        inp.focus()

    def _hide_input(self) -> None:
        self._pending_mode = ""
        self.add_class("input-hidden")

    # ── key handlers ──────────────────────────────────────────────────────

    def action_start_run(self) -> None:
        self._fixture_path = ""
        self._golden_path = ""
        self._show_input("Fixture path (fixture.json)…", _MODE_FIXTURE)

    def action_run_golden(self) -> None:
        self.notify("Running Stage 1 golden test…", severity="information")
        self.run_golden_test()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "harness-cmd-input":
            return
        value = event.value.strip()
        mode = self._pending_mode
        self._hide_input()

        if mode == _MODE_FIXTURE:
            self._fixture_path = value
            if value:
                self._show_input("Golden path (golden.json)…", _MODE_GOLDEN)
        elif mode == _MODE_GOLDEN:
            self._golden_path = value
            if value:
                self._show_input("Playbook dir path…", _MODE_PLAYBOOK)
        elif mode == _MODE_PLAYBOOK:
            if value and self._fixture_path and self._golden_path:
                self.notify("Running harness…", severity="information")
                self.run_fixture(self._fixture_path, self._golden_path, value)

    def on_key(self, event: Any) -> None:
        if not self.has_class("input-hidden") and getattr(event, "key", "") == "escape":
            self._hide_input()

    # ── golden test worker ─────────────────────────────────────────────────

    @work(thread=True)
    def run_golden_test(self) -> None:
        from pathlib import Path

        repo_root = Path(__file__).parents[5]
        fixture_path = repo_root / "examples" / "scn_ticket_summary_zh" / "harness" / "fixture.json"
        golden_path = repo_root / "examples" / "scn_ticket_summary_zh" / "harness" / "golden.json"
        playbook_dir = repo_root / "playbooks" / "pb_ticket_summary_zh"

        if not fixture_path.is_file():
            self.app.call_from_thread(
                self.notify, "Golden fixture not found", severity="error"
            )
            return

        self._run_harness_sync(fixture_path, golden_path, playbook_dir)

    # ── custom run worker ──────────────────────────────────────────────────

    @work(thread=True)
    def run_fixture(self, fixture: str, golden: str, playbook: str) -> None:
        from pathlib import Path

        self._run_harness_sync(Path(fixture), Path(golden), Path(playbook))

    def _run_harness_sync(
        self, fixture_path: Any, golden_path: Any, playbook_dir: Any
    ) -> None:
        from ...config import load_config
        from ...harness import load_fixture, load_golden, run_harness
        from ...memory.lance_store import LanceStore
        from ...memory.sqlite_store import SqliteStore
        from ...memory.storage_init import init_sqlite
        from ...orchestrator.types import load_playbook
        from ...providers import make_provider
        from ...redaction import Redactor
        from ...session import SessionManager

        cfg = load_config()
        kb_dir = cfg.home / "kb"
        kb_dir.mkdir(parents=True, exist_ok=True)

        try:
            fixture = load_fixture(fixture_path)
            golden = load_golden(golden_path)
            playbook = load_playbook(playbook_dir)

            sqlite = SqliteStore(init_sqlite(kb_dir / "sqlite.db"))
            lance = LanceStore.open_or_create(kb_dir / "lancedb", dim=768, embedding_model=cfg.embed_model)
            provider = make_provider(
                playbook.model.provider_id,
                kind=playbook.model.kind,
                api_key=cfg.anthropic_api_key,
            )
            embed_provider = make_provider("ollama-local", base_url=cfg.ollama_base_url)

            def embed_fn(text: str) -> list[float]:
                return embed_provider.embed([text], model=cfg.embed_model)[0]

            session_mgr = SessionManager(home=cfg.home)
            redactor = Redactor.from_yaml()

            result = run_harness(
                fixture=fixture,
                golden=golden,
                playbook=playbook,
                provider=provider,
                embed_fn=embed_fn,
                sqlite_store=sqlite,
                lance_store=lance,
                session_manager=session_mgr,
                redactor=redactor,
                owner="tui@opspilot",
            )

            score = result.scores.get("weighted", 0.0)
            passed = result.passed
            msg = f"{'✓ PASS' if passed else '✗ FAIL'} score={score:.3f} fixture={result.fixture_id}"
            sev = "information" if passed else "warning"
        except Exception as exc:  # noqa: BLE001
            msg = f"Harness error: {exc}"
            sev = "error"

        def refresh() -> None:
            self.notify(msg, severity=sev)
            dt = self.query_one(DataTable)
            dt.clear()
            self.load_results()

        self.app.call_from_thread(refresh)

    # ── load results ───────────────────────────────────────────────────────

    @work(thread=True)
    def load_results(self) -> None:
        from ...config import load_config

        cfg = load_config()
        rows: list[tuple[str, ...]] = []

        for results_file in sorted(cfg.home.rglob("results.jsonl")):
            try:
                with results_file.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        d = json.loads(line)
                        rows.append(
                            (
                                d.get("fixture_id", "—"),
                                d.get("playbook_id", "—"),
                                f"{d.get('weighted_score', 0):.3f}",
                                "✓" if d.get("pass") else "✗",
                                (d.get("run_at") or "")[:19],
                            )
                        )
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
