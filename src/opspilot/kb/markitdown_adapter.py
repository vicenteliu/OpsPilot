"""Convert non-markdown sources (PDF / DOCX / PPTX / XLSX / HTML / EPUB)
into markdown using `markitdown`. Plain `.md` / `.markdown` files pass
through verbatim.

Vision OFF (user decision #1, see docs/zh/design/STAGES.md §1.2): we never call a vision
provider on embedded images. Markitdown will leave images as alt-text /
placeholder references; we don't enhance them with LLM captions.

The adapter exposes one entry point — :func:`to_markdown` — returning a
small dataclass with the markdown body plus metadata callers need
(detected type, source bytes, suggested title). The metadata feeds
ingestion's `kb_documents` row.

Failure mode: hard fail (raise :class:`AdapterError`). Per spec design,
ingestion writes the failure into ``ingest_runs.error_summary`` rather
than silently skipping.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from markitdown import MarkItDown

from ..errors import OpsPilotError

# Extensions we route through markitdown's converter. ``.md``/``.markdown``
# bypass the converter entirely.
_MARKITDOWN_EXTS: Final[frozenset[str]] = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".pptx",
        ".ppt",
        ".xlsx",
        ".xls",
        ".html",
        ".htm",
        ".epub",
        ".rtf",
        ".csv",
        ".tsv",
        ".json",  # markitdown will pretty-print
        ".xml",
    }
)
_PASSTHROUGH_EXTS: Final[frozenset[str]] = frozenset({".md", ".markdown"})

# Magic-byte prefixes for cross-checking the extension. We only verify a
# handful of binary formats where a wrong extension is a real concern; for
# text formats the extension alone is fine.
_MAGIC_PREFIXES: Final[dict[str, bytes]] = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",  # zip container
    ".pptx": b"PK\x03\x04",
    ".xlsx": b"PK\x03\x04",
    ".epub": b"PK\x03\x04",
}


class AdapterError(OpsPilotError):
    """Raised when markitdown_adapter cannot produce markdown."""


@dataclass(frozen=True)
class AdapterResult:
    """Output of :func:`to_markdown`."""

    markdown: str
    detected_ext: str
    source_size_bytes: int
    title: str | None
    converted_via_markitdown: bool


def to_markdown(path: Path) -> AdapterResult:
    """Read ``path`` and return its markdown form.

    - ``.md`` / ``.markdown`` → returned as-is.
    - Anything in :data:`_MARKITDOWN_EXTS` → converted via markitdown.
    - Otherwise → :class:`AdapterError`.
    """
    if not path.is_file():
        raise AdapterError(f"not a file: {path}")

    ext = path.suffix.lower()
    size = path.stat().st_size

    if ext in _PASSTHROUGH_EXTS:
        return AdapterResult(
            markdown=path.read_text(encoding="utf-8"),
            detected_ext=ext,
            source_size_bytes=size,
            title=_first_h1(path.read_text(encoding="utf-8")),
            converted_via_markitdown=False,
        )

    if ext not in _MARKITDOWN_EXTS:
        raise AdapterError(
            f"unsupported file type for ingestion: {ext} ({path}); "
            f"supported: {sorted(_PASSTHROUGH_EXTS | _MARKITDOWN_EXTS)}"
        )

    _verify_magic(path, ext)

    try:
        result = MarkItDown().convert(str(path))
    except Exception as e:  # markitdown raises a wide variety of types
        raise AdapterError(f"markitdown failed to convert {path} ({ext}): {e}") from e

    md_text: str = getattr(result, "text_content", None) or getattr(result, "markdown", None) or ""
    if not md_text.strip():
        raise AdapterError(
            f"markitdown produced empty markdown for {path}; "
            "file may be image-only or password-protected"
        )

    title: str | None = getattr(result, "title", None) or _first_h1(md_text)

    return AdapterResult(
        markdown=md_text,
        detected_ext=ext,
        source_size_bytes=size,
        title=title,
        converted_via_markitdown=True,
    )


# ── Helpers ───────────────────────────────────────────────────────────


def _verify_magic(path: Path, ext: str) -> None:
    """Cross-check extension vs. magic bytes for binary formats.

    A mismatch usually means the file was renamed; surface that early
    so ingestion fails at the doorstep rather than producing garbage
    chunks downstream.
    """
    expected = _MAGIC_PREFIXES.get(ext)
    if expected is None:
        return
    with path.open("rb") as f:
        head = f.read(len(expected))
    if not head.startswith(expected):
        raise AdapterError(
            f"file {path} has extension {ext} but magic bytes {head!r} do not "
            f"match expected {expected!r}; refusing to ingest a likely "
            "mis-renamed file"
        )


def _first_h1(md: str) -> str | None:
    """Return the first ATX H1 (# Title) found, or None.

    Used as a fallback title when markitdown doesn't extract one.
    """
    for raw in md.splitlines():
        line = raw.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip() or None
    return None
