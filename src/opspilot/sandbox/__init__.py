"""OpsPilot Sandbox — L2 Docker hardened execution layer (PR-30).

Lifecycle: validate → dry_run → [approval?] → apply → record
"""

from .engine import SandboxEngine
from .gate import check_approval_required
from .types import ActionRequest, ActionResult, ApplyResult, DryRunPreview, RequestedPolicy

__all__ = [
    "SandboxEngine",
    "check_approval_required",
    "ActionRequest",
    "ActionResult",
    "ApplyResult",
    "DryRunPreview",
    "RequestedPolicy",
]
