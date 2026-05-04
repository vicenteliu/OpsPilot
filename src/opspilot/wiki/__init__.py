"""Wiki module — compounding knowledge layer (PR-19).

Implements wiki/ingest: takes an already-ingested KB document and produces
one ``summary`` wiki page, updates index.md and log.md, then optionally
registers the page back into the KB as a ``wiki_synthesis`` document.

query→page and lint are Stage 4 (PR-24 / PR-23).
"""

from .ingest import WikiIngestConfig, WikiIngestResult, ingest
from .page import WikiPage, read_page, write_page

__all__ = [
    "WikiIngestConfig",
    "WikiIngestResult",
    "WikiPage",
    "ingest",
    "read_page",
    "write_page",
]
