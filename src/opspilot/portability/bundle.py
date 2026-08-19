"""Export and import a knowledge bundle (ADR-0033).

**Backup is not export.** A **Session** is an append-only ledger whose value is
that it happened on this machine and was not edited; the moment it becomes a file
you can export, that guarantee is gone — what lands is a copy anyone can edit,
indistinguishable from the original on the way back. A **Consultation** is
withheld for a different reason: it is swept after 90 days anyway, so durability
is not what is being protected, but it collects pasted logs and configs with none
of the redaction a Work item passes through. Both travel only by whole-directory
cold backup, at the filesystem layer.

What travels here is **knowledge**, which is supposed to move: the KB, Skills,
Wiki pages and Memory.

Two shapes are deliberate.

**Per-domain native formats, not a uniform envelope.** Skills and Wiki pages are
already files, and converting them to JSON would destroy the property ADR-0027
depends on: a Skill is admitted through a pull request, and a pull request has to
be readable as a diff.

**The KB travels as text, never as chunks or vectors.** Chunks are an artefact of
the splitter and vectors are bound to an embedding model, so vectors carried to a
machine running a different model are noise. The receiver re-ingests.

One deviation from ADR-0033's letter, and it is the safer reading. The ADR says
the KB exports its *source documents*; the KB does not keep them — it records a
``source_path`` pointing at a file outside OpsPilot, and that file is **not
redacted**. So a document is reassembled from its stored chunks instead, which
are. Exporting what the KB actually holds beats exporting what it merely points
at.
"""

from __future__ import annotations

import json
import shutil
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..timeutil import now_rfc3339

MANIFEST_NAME = "manifest.json"
BUNDLE_VERSION = 1


@dataclass
class BundleStats:
    """What went in, or what came out."""

    kb_documents: int = 0
    skills: int = 0
    wiki_pages: int = 0
    memory_entries: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {
            "kb_documents": self.kb_documents,
            "skills": self.skills,
            "wiki_pages": self.wiki_pages,
            "memory_entries": self.memory_entries,
        }


def export_bundle(
    destination: Path,
    *,
    sqlite: Any | None = None,
    memory: Any | None = None,
    skills_dir: Path | None = None,
    wiki_root: Path | None = None,
    embedding_model: str | None = None,
    opspilot_version: str = "",
) -> BundleStats:
    """Write a ``.tar.gz`` bundle to *destination*. Returns what it contained."""
    stats = BundleStats()
    staging = destination.parent / f".{destination.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        if sqlite is not None:
            stats.kb_documents = _export_kb(sqlite, staging / "kb")
        if skills_dir is not None and skills_dir.is_dir():
            _copy_tree(skills_dir, staging / "skills")
            # Count Skills, not files. A skill directory may carry references or
            # assets, and the exporting and importing sides have to report the
            # same number for the same bundle.
            stats.skills = len(list((staging / "skills").rglob("SKILL.md")))
        if wiki_root is not None and wiki_root.is_dir():
            stats.wiki_pages = _copy_tree(wiki_root, staging / "wiki", suffix=".md")
        if memory is not None:
            stats.memory_entries = _export_memory(memory, staging / "memory" / "entries.jsonl")

        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "exported_at": now_rfc3339(),
            "opspilot_version": opspilot_version,
            "counts": stats.as_dict(),
            # The receiver needs this to know whether to recompute — and the
            # answer is always yes, because vectors are not carried at all.
            "kb_embedding_model": embedding_model,
            "excluded": {
                "sessions": "append-only ledger; travels by whole-directory backup only",
                "consultations": "unredacted pasted logs; travels by whole-directory backup only",
            },
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        destination.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(destination, "w:gz") as tar:
            for item in sorted(staging.rglob("*")):
                if item.is_file():
                    tar.add(item, arcname=str(item.relative_to(staging)))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return stats


def import_bundle(
    source: Path,
    *,
    staging_dir: Path,
    memory: Any | None = None,
    actor: str = "",
) -> BundleStats:
    """Unpack *source* into *staging_dir*; restore Memory entries directly.

    **Skills, Wiki pages and KB documents are staged, never installed.** ADR-0027
    is specific that admission *is* a pull request, and a tar unpacked onto disk
    produces no commit and no diff — so "lands as a draft" would be a phrase
    rather than a gate. Moving a staged Skill into ``agent_skills/`` is the
    commit, and that commit is the admission.

    Memory is different, and only for the case ADR-0033 scoped: **restoring your
    own bundle.** Entries come back with the actor and timestamp of the original
    admission, because that record *is* the admission — it is not being made
    again. Adopting another team's entries is a different decision and is not
    this function.
    """
    stats = BundleStats()
    staging_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source, "r:gz") as tar:
        _safe_extract(tar, staging_dir)

    manifest_path = staging_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"{source} is not an OpsPilot bundle: no {MANIFEST_NAME}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("bundle_version") != BUNDLE_VERSION:
        raise ValueError(f"bundle version {manifest.get('bundle_version')} is not {BUNDLE_VERSION}")

    stats.kb_documents = len(list((staging_dir / "kb").glob("*.md")))
    stats.skills = len(list((staging_dir / "skills").rglob("SKILL.md")))
    stats.wiki_pages = len(list((staging_dir / "wiki").rglob("*.md")))
    if stats.kb_documents:
        stats.notes.append(
            f"{stats.kb_documents} KB document(s) staged — run `opspilot ingest` on "
            f"{staging_dir / 'kb'} to re-chunk and re-embed under this machine's model"
        )
    if stats.skills:
        stats.notes.append(
            f"{stats.skills} Skill(s) staged — review and commit them into agent_skills/; "
            "that commit is the admission (ADR-0027)"
        )
    if stats.wiki_pages:
        stats.notes.append(f"{stats.wiki_pages} Wiki page(s) staged for review")

    entries_path = staging_dir / "memory" / "entries.jsonl"
    if memory is not None and entries_path.is_file():
        stats.memory_entries = _restore_memory(memory, entries_path)
        stats.notes.append(
            f"{stats.memory_entries} Memory entr(y/ies) restored with their original actors"
        )
    return stats


# ── internals ─────────────────────────────────────────────────────────


def _export_kb(sqlite: Any, out_dir: Path) -> int:
    """One markdown file per document, reassembled from its stored chunks."""
    rows = sqlite._conn.execute(  # noqa: SLF001 — no public listing helper yet
        "SELECT id, title, source_path, language, namespace FROM kb_documents ORDER BY id"
    ).fetchall()
    if not rows:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for row in rows:
        doc_id, title, source_path, language, namespace = (row[k] for k in range(5))
        chunks = sqlite.get_chunks_by_document_id(str(doc_id))
        if not chunks:
            continue
        body = "\n\n".join(str(c["content"]) for c in sorted(chunks, key=lambda c: c["seq"]))
        header = (
            "---\n"
            f"title: {json.dumps(title, ensure_ascii=False)}\n"
            f"original_source_path: {json.dumps(source_path, ensure_ascii=False)}\n"
            f"language: {language}\n"
            f"namespace: {namespace}\n"
            "note: reassembled from redacted chunks; re-ingest to rebuild chunks and vectors\n"
            "---\n\n"
        )
        (out_dir / f"{doc_id}.md").write_text(header + body + "\n", encoding="utf-8")
        count += 1
    return count


def _export_memory(memory: Any, out_path: Path) -> int:
    entries = memory.list_entries(include_retired=True, limit=100_000)
    if not entries:
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(_entry_dict(e), ensure_ascii=False) + "\n")
    return len(entries)


def _entry_dict(e: Any) -> dict[str, Any]:
    return {
        "id": e.id,
        "statement": e.statement,
        "reason": e.reason,
        "actor": e.actor,
        "created_at": e.created_at,
        "review_after": e.review_after,
        "asset_id": e.asset_id,
        "scope": e.scope,
        "source_ref": e.source_ref,
        "superseded_by": e.superseded_by,
        "superseded_at": e.superseded_at,
        "archived_at": e.archived_at,
    }


def _restore_memory(memory: Any, entries_path: Path) -> int:
    """Re-insert rows verbatim, skipping ids that are already here.

    Verbatim on purpose: an entry's actor and timestamp *are* the record of its
    admission, and a restore is not a second one. Re-admitting through
    ``admit()`` would stamp the restoring operator and today's date over the
    person and moment that actually decided.
    """
    restored = 0
    with memory._lock:  # noqa: SLF001 — a restore is a bulk write, one transaction
        for line in entries_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            cur = memory._conn.execute(  # noqa: SLF001
                "INSERT OR IGNORE INTO memory_entries "
                "(id, statement, reason, actor, created_at, review_after, asset_id, scope, "
                "source_ref, superseded_by, superseded_at, archived_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(
                    e.get(k)
                    for k in (
                        "id",
                        "statement",
                        "reason",
                        "actor",
                        "created_at",
                        "review_after",
                        "asset_id",
                        "scope",
                        "source_ref",
                        "superseded_by",
                        "superseded_at",
                        "archived_at",
                    )
                ),
            )
            restored += cur.rowcount
        memory._conn.commit()  # noqa: SLF001
    return restored


def _copy_tree(src: Path, dst: Path, *, suffix: str | None = None) -> int:
    count = 0
    for item in sorted(src.rglob("*")):
        if not item.is_file() or (suffix and item.suffix != suffix):
            continue
        target = dst / item.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        count += 1
    return count


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract, refusing any member that would escape *dest*."""
    dest = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        # is_relative_to, not a string prefix: "/x/import-evil" starts with
        # "/x/import" and is not inside it.
        if not target.is_relative_to(dest):
            raise ValueError(f"bundle member escapes the staging directory: {member.name}")
        if member.issym() or member.islnk():
            raise ValueError(f"bundle contains a link, which is not allowed: {member.name}")
    tar.extractall(dest, filter="data")
