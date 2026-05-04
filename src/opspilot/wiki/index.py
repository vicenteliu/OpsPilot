"""Wiki index.md and log.md maintenance (PR-19).

Both files are append-friendly text files maintained under ``wiki_root``:

* ``index.md`` — one bullet per live page, machine-parseable format.
* ``log.md``   — append-only record of every ingest/update operation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..timeutil import now_rfc3339
from .page import WikiPage

# Regex for one index entry: ``- [[slug]] — summary · `tags` · classified X``
_INDEX_RE = re.compile(r"^- \[\[(\S+)\]\]")


@dataclass
class WikiLogEntry:
    op: str  # "ingest" | "update" | "archive"
    subject: str  # e.g. doc_id or page slug
    pages_created: int = 0
    pages_updated: int = 0
    pages_archived: int = 0
    session_id: str | None = None
    notes: str | None = None


def update_index(wiki_root: Path, page: WikiPage) -> None:
    """Add or replace the entry for *page* in ``wiki_root/index.md``."""
    index_path = wiki_root / "index.md"

    tag_str = ", ".join(f"`{t}`" for t in page.tags) if page.tags else ""
    entry = (
        f"- [[{page.slug}]] — {page.summary}"
        + (f" · {tag_str}" if tag_str else "")
        + f" · classified {page.classification}\n"
    )

    if not index_path.exists():
        # Bootstrap from template or create empty
        tmpl = wiki_root / "templates" / "index.template.md"
        base = tmpl.read_text(encoding="utf-8") if tmpl.exists() else "# Wiki Index\n\n"
        index_path.write_text(base, encoding="utf-8")

    text = index_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Replace existing entry for this slug, or append.
    for i, line in enumerate(lines):
        m = _INDEX_RE.match(line)
        if m and m.group(1) == page.slug:
            lines[i] = entry
            index_path.write_text("".join(lines), encoding="utf-8")
            return

    # New entry — append under matching kind heading or at end.
    if not text.endswith("\n"):
        text += "\n"
    index_path.write_text(text + entry, encoding="utf-8")


def append_log(wiki_root: Path, entry: WikiLogEntry) -> None:
    """Append a structured entry to ``wiki_root/log.md``."""
    log_path = wiki_root / "log.md"

    if not log_path.exists():
        tmpl = wiki_root / "templates" / "log.template.md"
        base = tmpl.read_text(encoding="utf-8") if tmpl.exists() else "# Wiki Log\n\n"
        log_path.write_text(base, encoding="utf-8")

    now = now_rfc3339()
    lines = [
        f"\n## [{now}] {entry.op} | {entry.subject}\n",
        f"- by: wiki-maintainer-skill@pr-19\n",
    ]
    if entry.session_id:
        lines.append(f"- session_id: {entry.session_id}\n")
    lines.append(
        f"- pages_touched: {entry.pages_created + entry.pages_updated + entry.pages_archived}"
        f" ({entry.pages_created} created"
        f" / {entry.pages_updated} updated"
        f" / {entry.pages_archived} archived)\n"
    )
    if entry.notes:
        lines.append(f"- notes: {entry.notes}\n")

    with log_path.open("a", encoding="utf-8") as f:
        f.writelines(lines)
