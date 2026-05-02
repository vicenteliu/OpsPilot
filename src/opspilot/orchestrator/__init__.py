"""Orchestrator package — runs playbooks against a session.

PR-7 ships:

* :class:`PlaybookSpec`, :class:`RunRequest`, :class:`RunResult` — data
  contracts shared by the CLI and the orchestrator.
* :func:`make_kb_search_tool` — wires PR-4 retrieval into a ToolDef the
  LLM can tool-call.
* :func:`run_ticket_summary` — main loop for ``pb_ticket_summary_zh``;
  closes Stage 1's end-to-end exit criterion.
"""

from .errors import OrchestratorError, PlaybookError
from .ticket_summary import run_ticket_summary
from .tools import KBSearchHit, make_kb_search_tool
from .types import PlaybookSpec, RunRequest, RunResult, load_playbook

__all__ = [
    "KBSearchHit",
    "OrchestratorError",
    "PlaybookError",
    "PlaybookSpec",
    "RunRequest",
    "RunResult",
    "load_playbook",
    "make_kb_search_tool",
    "run_ticket_summary",
]
