"""The SSC handbook as the KB's source (ADR-0038): which pages, and their keys (#226)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from opspilot.kb.ingestion import IngestConfig, ingest
from opspilot.kb.lance_store import LanceStore
from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.ssc import ssc_pages
from opspilot.kb.storage_init import init_sqlite
from opspilot.redaction import Redactor

DIM = 768
EMBED_MODEL = "ollama-local/test-embed@2026-04"


def _embed(text: str) -> list[float]:
    return [1.0] + [0.0] * (DIM - 1)


def _page(root: Path, rel: str, kind: str | None, body: str = "Some operating knowledge.") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    head = f"---\nkind: {kind}\nsummary: x\n---\n" if kind else ""
    path.write_text(f"{head}# {path.stem}\n\n{body}\n", encoding="utf-8")


def _ssc(root: Path) -> Path:
    """A small tree shaped like sysadmin-self-cultivation."""
    for rel, kind in [
        ("endpoint/encryption-and-keys.md", "companion"),
        ("cross-cutting/m365-support.md", "support-note"),
        ("00-the-operating-model.md", "note"),
        ("walkthrough/01-the-network.en.md", "walkthrough"),
        ("walkthrough/01-the-network.zh.md", "walkthrough"),  # the Chinese twin
        ("CONTENTS.md", "index"),
        ("ROADMAP.md", "roadmap"),
        ("cross-cutting/interview/identity.md", "interview"),
        ("docs/adr/0001-a-decision.md", "note"),  # SSC's own ADRs
        ("docs/zh/CONTENTS.md", "index"),
        (".claude/skills/x.md", "note"),
        ("site/README.md", "note"),
        ("tools/floor/README.md", "note"),
    ]:
        _page(root, rel, kind)
    _page(root, "README.md", None)  # the front door carries no frontmatter
    return root


def test_ssc_pages_are_the_english_content_pages(tmp_path: Path) -> None:
    root = _ssc(tmp_path / "ssc")
    assert [p.relative_to(root).as_posix() for p in ssc_pages(root)] == [
        "00-the-operating-model.md",
        "cross-cutting/m365-support.md",
        "endpoint/encryption-and-keys.md",
        "walkthrough/01-the-network.en.md",
    ]


def _source_paths(sqlite: SqliteStore) -> set[str]:
    return {r[0] for r in sqlite._conn.execute("SELECT source_path FROM kb_documents")}


def _stores(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    return sqlite, lance


def test_a_page_is_keyed_by_its_path_inside_the_handbook_wherever_it_is_checked_out(
    tmp_path: Path,
) -> None:
    sqlite, lance = _stores(tmp_path)
    first = _ssc(tmp_path / "one" / "ssc")
    cfg = IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM, source_root=first)
    stats = ingest(
        ssc_pages(first),
        sqlite=sqlite,
        lance=lance,
        redactor=Redactor.from_yaml(),
        embed_fn=_embed,
        config=cfg,
    )
    assert stats.docs_succeeded == 4
    paths = _source_paths(sqlite)
    assert "endpoint/encryption-and-keys.md" in paths and len(paths) == 4

    # The same handbook checked out elsewhere is the same pages, not four more.
    second = tmp_path / "two" / "ssc"
    shutil.copytree(first, second)
    again = ingest(
        ssc_pages(second),
        sqlite=sqlite,
        lance=lance,
        redactor=Redactor.from_yaml(),
        embed_fn=_embed,
        config=IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM, source_root=second),
    )
    assert all(f.chunks_skipped_unchanged for f in again.files)
    assert _source_paths(sqlite) == paths


def test_cli_dry_run_lists_the_pages_and_ingests_nothing(tmp_path: Path) -> None:
    from opspilot import cli

    root = _ssc(tmp_path / "ssc")
    result = CliRunner().invoke(
        cli.app, ["kb", "ingest", "--profile", "ssc", "--source", str(root), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "4 pages" in result.output
    assert "endpoint/encryption-and-keys.md" in result.output
    assert "CONTENTS.md" not in result.output


def test_a_kind_line_in_the_body_is_not_the_page_s_kind(tmp_path: Path) -> None:
    root = tmp_path / "ssc"
    path = root / "cross-cutting" / "yaml-basics.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nsummary: no kind here\n---\n# YAML\n\nkind: companion\n\n---\n", encoding="utf-8"
    )
    assert ssc_pages(root) == []  # no kind in its front matter: not a content page


def test_a_page_outside_the_root_fails_with_the_reason(tmp_path: Path) -> None:
    import pytest

    from opspilot.kb.ingestion import _source_key

    root = tmp_path / "ssc"
    root.mkdir()
    outside = tmp_path / "elsewhere.md"
    outside.write_text("x", encoding="utf-8")
    (root / "linked.md").symlink_to(outside)
    with pytest.raises(ValueError, match="outside the source root"):
        _source_key(root / "linked.md", IngestConfig(source_root=root))


def test_cli_names_kb_documents_the_handbook_build_no_longer_has(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from opspilot import cli

    root = _ssc(tmp_path / "ssc")
    _page(root, "endpoint/management.md", "companion")
    sqlite, lance = _stores(tmp_path)
    ingest(
        ssc_pages(root),
        sqlite=sqlite,
        lance=lance,
        redactor=Redactor.from_yaml(),
        embed_fn=_embed,
        config=IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM, source_root=root),
    )
    (root / "endpoint" / "management.md").unlink()  # renamed or removed in SSC
    monkeypatch.setattr(cli, "_ingest_and_report", lambda *a, **k: sqlite)
    result = CliRunner().invoke(
        cli.app, ["kb", "ingest", "--profile", "ssc", "--source", str(root)]
    )
    assert result.exit_code == 0, result.output
    assert "1 documents in opspilot:public-kb are not pages of this handbook build" in result.output
    assert "endpoint/management.md" in result.output
