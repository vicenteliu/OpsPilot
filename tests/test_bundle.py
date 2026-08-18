"""Export and import a knowledge bundle (ADR-0033).

**Backup is not export.** A Session is an append-only ledger whose value is that
it happened here and was not edited — the moment it becomes an exportable file
that guarantee is gone. A Consultation is withheld for a different reason: it is
swept anyway, so durability is not the point, but it holds pasted logs that never
passed a Work item's redaction. Both travel by whole-directory backup only, and a
test pins that neither appears in a bundle.

What travels is knowledge, in **per-domain native formats** — Skills stay files,
because ADR-0027 admits them through a pull request and a pull request has to be
readable as a diff.
"""

from __future__ import annotations

import json
import sqlite3
import tarfile
from pathlib import Path

import pytest

from opspilot.memory import MemoryStore
from opspilot.portability import MANIFEST_NAME, export_bundle, import_bundle


@pytest.fixture
def memory(tmp_path: Path) -> MemoryStore:
    store = MemoryStore(sqlite3.connect(tmp_path / "a.db"))
    store.admit(
        statement="Never restart the ESXi cluster on a Tuesday evening",
        reason="finance runs its month-end batch",
        actor="user:alice",
        scope="dc-1",
    )
    store.admit(
        statement="No production change on a Friday",
        reason="nobody to roll it back",
        actor="user:bob",
    )
    return store


def _skills(tmp_path: Path) -> Path:
    d = tmp_path / "agent_skills" / "vpn-auth-failures"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nid: vpn-auth-failures\n---\n\nProcedure.\n", encoding="utf-8")
    return tmp_path / "agent_skills"


def _bundle(tmp_path: Path, memory: MemoryStore) -> Path:
    dest = tmp_path / "bundle.tar.gz"
    export_bundle(dest, memory=memory, skills_dir=_skills(tmp_path), embedding_model="e5-small")
    return dest


class TestExport:
    def test_a_skill_travels_as_a_file(self, tmp_path: Path, memory: MemoryStore) -> None:
        """JSON would destroy the property ADR-0027 depends on: a readable diff."""
        with tarfile.open(_bundle(tmp_path, memory)) as tar:
            names = tar.getnames()
        assert "skills/vpn-auth-failures/SKILL.md" in names

    def test_sessions_and_consultations_are_absent(
        self, tmp_path: Path, memory: MemoryStore
    ) -> None:
        with tarfile.open(_bundle(tmp_path, memory)) as tar:
            names = " ".join(tar.getnames())
        assert "session" not in names and "consultation" not in names

    def test_the_manifest_says_what_was_left_out_and_why(
        self, tmp_path: Path, memory: MemoryStore
    ) -> None:
        with tarfile.open(_bundle(tmp_path, memory)) as tar:
            manifest = json.loads(tar.extractfile(MANIFEST_NAME).read())  # type: ignore[union-attr]
        assert manifest["counts"]["memory_entries"] == 2
        assert "append-only" in manifest["excluded"]["sessions"]
        assert "unredacted" in manifest["excluded"]["consultations"]

    def test_the_embedding_model_is_recorded(self, tmp_path: Path, memory: MemoryStore) -> None:
        """The receiver needs it to know whether to recompute — the answer is always yes."""
        with tarfile.open(_bundle(tmp_path, memory)) as tar:
            manifest = json.loads(tar.extractfile(MANIFEST_NAME).read())  # type: ignore[union-attr]
        assert manifest["kb_embedding_model"] == "e5-small"

    def test_no_vectors_travel(self, tmp_path: Path, memory: MemoryStore) -> None:
        with tarfile.open(_bundle(tmp_path, memory)) as tar:
            names = " ".join(tar.getnames())
        assert "lance" not in names and ".vector" not in names


class TestImport:
    def test_memory_comes_back_with_its_original_actor(
        self, tmp_path: Path, memory: MemoryStore
    ) -> None:
        """An entry's actor and timestamp *are* the record of its admission.

        Re-admitting would stamp the restoring operator over the person who
        actually decided.
        """
        src = _bundle(tmp_path, memory)
        fresh = MemoryStore(sqlite3.connect(tmp_path / "b.db"))
        stats = import_bundle(src, staging_dir=tmp_path / "staging", memory=fresh)
        assert stats.memory_entries == 2
        assert {e.actor for e in fresh.list_entries()} == {"user:alice", "user:bob"}

    def test_restoring_twice_adds_nothing(self, tmp_path: Path, memory: MemoryStore) -> None:
        src = _bundle(tmp_path, memory)
        fresh = MemoryStore(sqlite3.connect(tmp_path / "b.db"))
        import_bundle(src, staging_dir=tmp_path / "s1", memory=fresh)
        again = import_bundle(src, staging_dir=tmp_path / "s2", memory=fresh)
        assert again.memory_entries == 0
        assert len(fresh.list_entries()) == 2

    def test_skills_are_staged_never_installed(self, tmp_path: Path, memory: MemoryStore) -> None:
        """A tar unpacked onto disk produces no commit and no diff (ADR-0027)."""
        src = _bundle(tmp_path, memory)
        staging = tmp_path / "staging"
        stats = import_bundle(src, staging_dir=staging, memory=None)
        assert (staging / "skills" / "vpn-auth-failures" / "SKILL.md").is_file()
        assert any("that commit is the admission" in n for n in stats.notes)

    def test_a_non_bundle_is_refused(self, tmp_path: Path) -> None:
        bogus = tmp_path / "bogus.tar.gz"
        (tmp_path / "x.txt").write_text("hi", encoding="utf-8")
        with tarfile.open(bogus, "w:gz") as tar:
            tar.add(tmp_path / "x.txt", arcname="x.txt")
        with pytest.raises(ValueError, match="not an OpsPilot bundle"):
            import_bundle(bogus, staging_dir=tmp_path / "s")

    def test_a_member_escaping_the_staging_dir_is_refused(self, tmp_path: Path) -> None:
        evil = tmp_path / "evil.tar.gz"
        (tmp_path / "payload").write_text("bad", encoding="utf-8")
        with tarfile.open(evil, "w:gz") as tar:
            tar.add(tmp_path / "payload", arcname="../escaped")
        with pytest.raises(ValueError, match="escapes the staging directory"):
            import_bundle(evil, staging_dir=tmp_path / "s")
