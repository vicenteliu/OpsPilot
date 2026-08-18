"""OpsPilot Sandbox — L2 Docker hardened execution layer (PR-30).

Lifecycle: validate → dry_run → [approval?] → apply → record

A Session reaches this through :mod:`opspilot.sandbox.proposals`, which is the
one notch ADR-0028 closed: a Session *proposes*, a human *executes*.
"""

from .engine import SandboxEngine
from .gate import check_approval_required
from .proposals import (
    DIAGNOSTIC_TYPES,
    Preview,
    ProposalError,
    execute_proposal,
    preview_proposal,
    record_proposals,
    to_request,
)
from .types import ActionRequest, ActionResult, ApplyResult, DryRunPreview, RequestedPolicy

__all__ = [
    "DIAGNOSTIC_TYPES",
    "ActionRequest",
    "ActionResult",
    "ApplyResult",
    "DryRunPreview",
    "Preview",
    "ProposalError",
    "RequestedPolicy",
    "SandboxEngine",
    "check_approval_required",
    "execute_proposal",
    "preview_proposal",
    "record_proposals",
    "to_request",
]
