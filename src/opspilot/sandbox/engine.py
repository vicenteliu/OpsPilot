"""SandboxEngine — orchestrates validate → dry_run → [approval] → apply."""

from __future__ import annotations

from .docker_l2 import _DEFAULT_IMAGE, dry_run_preview, run_l2
from .docker_l3 import run_l3
from .gate import check_approval_required
from .types import ActionRequest, ActionResult, Level


class SandboxEngine:
    def __init__(self, image: str = _DEFAULT_IMAGE, level: Level = "l2") -> None:
        self._image = image
        self._level = level
        # L3 swaps the OCI runtime to gVisor; L2 leaves it at the daemon default.
        self._runtime = "runsc" if level == "l3" else None

    def dry_run(self, request: ActionRequest) -> ActionResult:
        approval = check_approval_required(request)
        preview = dry_run_preview(request, self._image, self._runtime)
        return ActionResult(
            action_id=request.id,
            status="dry_run",
            dry_run_preview=preview,
            approval_required=approval,
        )

    def execute(self, request: ActionRequest, *, force_approve: bool = False) -> ActionResult:
        """Execute the action.

        If dry_run=True (default), returns a dry-run preview without touching Docker.
        If dry_run=False, runs in the configured backend (L2 Docker hardened, or L3
        gVisor). Approval-required actions are blocked unless force_approve=True.
        """
        approval = check_approval_required(request)

        if request.dry_run:
            return self.dry_run(request)

        if approval and not force_approve:
            return ActionResult(
                action_id=request.id,
                status="approval_pending",
                approval_required=True,
                rejection_reason="Action requires approval. Re-run with --approve to proceed.",
            )

        preview = dry_run_preview(request, self._image, self._runtime)
        result = (
            run_l3(request, self._image) if self._level == "l3" else run_l2(request, self._image)
        )

        if result.timeout_killed or result.oom_killed or result.exit_code != 0:
            status = "failed"
        else:
            status = "applied"

        return ActionResult(
            action_id=request.id,
            status=status,
            dry_run_preview=preview,
            apply_result=result,
            approval_required=approval,
        )
