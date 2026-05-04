"""Wiki module — compounding knowledge layer (PR-19 / PR-23 / PR-24).

PR-19: ingest — KB document → wiki summary page.
PR-23: lint — pure-static checks (orphan, broken_link, redaction_warning,
       schema_invalid).
PR-24: query_to_page — archived session response → wiki synthesis page.
"""

from .ingest import WikiIngestConfig, WikiIngestResult, ingest
from .lint import LintIssue, lint_wiki
from .page import WikiPage, read_page, write_page
from .query_to_page import QueryToPageConfig, QueryToPageResult, query_to_page, scan_and_convert

__all__ = [
    "LintIssue",
    "QueryToPageConfig",
    "QueryToPageResult",
    "WikiIngestConfig",
    "WikiIngestResult",
    "WikiPage",
    "ingest",
    "lint_wiki",
    "query_to_page",
    "read_page",
    "scan_and_convert",
    "write_page",
]
