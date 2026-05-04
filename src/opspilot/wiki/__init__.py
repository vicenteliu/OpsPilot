"""Wiki module — compounding knowledge layer (PR-19 / PR-23).

Implements wiki/ingest: takes an already-ingested KB document and produces
one ``summary`` wiki page, updates index.md and log.md, then optionally
registers the page back into the KB as a ``wiki_synthesis`` document.

lint (PR-23): pure-static checks — orphan, broken_link, redaction_warning,
schema_invalid (missing sections, parse errors, slug collisions).
query→page is Stage 4 (PR-24).
"""

from .ingest import WikiIngestConfig, WikiIngestResult, ingest
from .lint import LintIssue, lint_wiki
from .page import WikiPage, read_page, write_page

__all__ = [
    "LintIssue",
    "WikiIngestConfig",
    "WikiIngestResult",
    "WikiPage",
    "ingest",
    "lint_wiki",
    "read_page",
    "write_page",
]
