"""Content-addressed artifact store per session.

Layout::

    <session_dir>/artifacts/
        <art_id>.<ext>          ── content
        <art_id>.meta.yaml      ── sidecar metadata

``art_id`` = ``art_<sha256[:16]>`` of the content bytes (per
``docs/specs/memory/schemas/kb-chunk.schema.json#/properties/content_artifact_id``
pattern). Same bytes always map to the same id, so the store is
inherently de-duplicating.

Sidecar meta is yaml per the spec template style; see
``docs/specs/session/SPEC.md §4``.
"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

import yaml

from ..timeutil import now_rfc3339
from .errors import SessionError

_ARTIFACT_HASH_LEN: Final[int] = 16


# ── Public dataclass ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ArtifactMeta:
    """Sidecar fields for one artifact."""

    artifact_id: str
    kind: str  # MIME-style or 'tool'/'response'/'attachment' label
    source: str  # e.g. 'tool:bash', 'model:assistant', 'user:upload'
    created_at: str
    size_bytes: int
    sha256: str  # full hex digest (the prefix is in the id)
    encoding: str  # 'binary' | 'utf-8'
    extension: str  # leading-dot ext stored on disk

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# ── Store ─────────────────────────────────────────────────────────────


class ArtifactStore:
    """Per-session content-addressed file store.

    Construction is cheap (just stores the dir); on first ``put`` the
    ``artifacts/`` subdirectory is created.
    """

    def __init__(self, session_dir: Path) -> None:
        self._dir = session_dir / "artifacts"

    @property
    def dir(self) -> Path:
        return self._dir

    # ── Writes ───────────────────────────────────────────────────────

    def put(
        self,
        content: bytes | str,
        *,
        kind: str,
        source: str,
        extension: str | None = None,
    ) -> ArtifactMeta:
        """Write ``content`` to the store and return its sidecar meta.

        Args:
            content:    bytes or str (auto-encoded as UTF-8 if str).
            kind:       MIME-style identifier (e.g. ``"text/plain"``,
                        ``"application/json"``, or a coarser label like
                        ``"tool"``).
            source:     Free-form origin (e.g. ``"tool:bash"``).
            extension:  Override the inferred file extension (must
                        include leading dot). Inferred from ``kind``
                        via :mod:`mimetypes` when omitted.

        Idempotent: identical ``content`` always maps to the same
        ``art_id``; if the file already exists we keep the **first**
        sidecar (same content shouldn't have conflicting metadata in
        practice; see :meth:`put_force_overwrite_meta` for that case).
        """
        if isinstance(content, str):
            data = content.encode("utf-8")
            encoding = "utf-8"
        else:
            data = bytes(content)
            encoding = "binary"

        digest = hashlib.sha256(data).hexdigest()
        art_id = f"art_{digest[:_ARTIFACT_HASH_LEN]}"
        ext = extension or _ext_for(kind, encoding)

        self._dir.mkdir(parents=True, exist_ok=True)
        body_path = self._dir / f"{art_id}{ext}"
        meta_path = self._dir / f"{art_id}.meta.yaml"

        if not body_path.exists():
            body_path.write_bytes(data)

        # If meta already exists (re-put of identical content) keep it;
        # the deterministic id implies the same content, so meta should
        # also be effectively the same.
        if meta_path.exists():
            return _read_meta(meta_path)

        meta = ArtifactMeta(
            artifact_id=art_id,
            kind=kind,
            source=source,
            created_at=now_rfc3339(),
            size_bytes=len(data),
            sha256=f"sha256:{digest}",
            encoding=encoding,
            extension=ext,
        )
        _write_meta(meta_path, meta)
        return meta

    # ── Reads ────────────────────────────────────────────────────────

    def get_meta(self, art_id: str) -> ArtifactMeta:
        """Return the sidecar meta for ``art_id``."""
        path = self._dir / f"{art_id}.meta.yaml"
        if not path.is_file():
            raise SessionError(f"artifact meta not found: {art_id} ({path})")
        return _read_meta(path)

    def read_bytes(self, art_id: str) -> bytes:
        """Return the artifact bytes for ``art_id``."""
        meta = self.get_meta(art_id)
        body_path = self._dir / f"{art_id}{meta.extension}"
        if not body_path.is_file():
            raise SessionError(f"artifact body missing for {art_id}: {body_path}")
        return body_path.read_bytes()

    def read_text(self, art_id: str) -> str:
        """Return the artifact decoded as UTF-8.

        Raises if the artifact was stored as binary; callers should use
        :meth:`read_bytes` in that case.
        """
        meta = self.get_meta(art_id)
        if meta.encoding != "utf-8":
            raise SessionError(f"{art_id} was stored as {meta.encoding}; use read_bytes() instead")
        return self.read_bytes(art_id).decode("utf-8")

    def exists(self, art_id: str) -> bool:
        return (self._dir / f"{art_id}.meta.yaml").is_file()

    def list_ids(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        return sorted(p.stem.removesuffix(".meta") for p in self._dir.glob("art_*.meta.yaml"))


# ── Helpers ───────────────────────────────────────────────────────────


def _ext_for(kind: str, encoding: str) -> str:
    """Pick a file extension for the on-disk body.

    Priority:
    1. If ``kind`` looks like a MIME type, map via ``mimetypes``.
    2. Otherwise default to ``.txt`` for utf-8 or ``.bin`` for binary.
    """
    if "/" in kind:
        guess = mimetypes.guess_extension(kind)
        if guess:
            return guess
    return ".txt" if encoding == "utf-8" else ".bin"


def _write_meta(path: Path, meta: ArtifactMeta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            meta.to_dict(),
            f,
            sort_keys=False,
            allow_unicode=True,
        )


def _read_meta(path: Path) -> ArtifactMeta:
    with path.open(encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    return ArtifactMeta(**d)
