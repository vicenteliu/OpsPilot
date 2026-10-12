"""The SSC handbook as the KB's single source (ADR-0038): which of its files are pages.

`sysadmin-self-cultivation` is markdown with a YAML front matter on every page
(`kind: companion`, `kind: note`, ...). The profile takes the English pages
that carry operating knowledge and leaves the scaffolding: the Chinese mirror
and SSC's own ADRs under `docs/` (a Chinese KB is #233), tooling directories,
navigation pages, and interview prep. The rule lives here, not in SSC: a
handbook that knew its consumer would be coupled to it (ADR-0038).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

# Not handbook pages: SSC's own docs and Chinese mirror, agent config, the site
# build, and tooling.
_SKIP_DIRS: Final = frozenset({"docs", "site", "tools", "__pycache__"})
# Navigation and planning, and interview questions: pages, but not operating
# knowledge a Work item could be answered from.
_SKIP_KINDS: Final = frozenset({"index", "roadmap", "interview"})
_FRONT_MATTER: Final = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_KIND: Final = re.compile(r"^kind:\s*(\S+)", re.M)


def ssc_pages(root: Path) -> list[Path]:
    """The handbook's English content pages under ``root``, in path order."""
    pages = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part.startswith(".") or part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if path.name.endswith(".zh.md"):
            continue
        front = _FRONT_MATTER.match(path.read_text(encoding="utf-8", errors="replace"))
        kind = _KIND.search(front.group(1)) if front else None
        if kind is None or kind.group(1) in _SKIP_KINDS:
            continue  # no front matter (the README front door), or not a content page
        pages.append(path)
    return sorted(pages, key=lambda p: p.relative_to(root).as_posix())
