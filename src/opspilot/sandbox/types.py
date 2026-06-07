from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# Isolation backend level. L2 = Docker hardened (shared host kernel);
# L3 = L2 + gVisor runsc (user-space kernel). Selected operationally, not by
# the proposing model — see ADR-0009.
Level = Literal["l2", "l3"]


class NetworkPolicy(BaseModel):
    mode: Literal["deny-all", "allowlist", "open"] = "deny-all"
    egress: list[dict[str, str]] = []


class FsMount(BaseModel):
    source: str
    target: str
    mode: Literal["ro", "rw"] = "ro"


class FsPolicy(BaseModel):
    rootfs: Literal["read_only", "rw"] = "read_only"
    workdir: str = "/work"
    mounts: list[FsMount] = []


class ResourcePolicy(BaseModel):
    cpu: str = "1"
    memory: str = "512Mi"
    disk_tmpfs: str = "64Mi"
    pids: int = 128
    timeout_seconds: int = 30


class RequestedPolicy(BaseModel):
    network: NetworkPolicy = NetworkPolicy()
    fs: FsPolicy = FsPolicy()
    resource: ResourcePolicy = ResourcePolicy()
    secrets: list[str] = []


class RollbackHint(BaseModel):
    irreversible: bool = False
    steps: list[str] = []


class ActionRequest(BaseModel):
    id: str
    session_id: str
    proposed_by: str
    created_at: str
    type: Literal["shell", "script", "http", "sql_readonly", "workflow_dryrun"]
    payload: dict[str, Any]
    requested_policy: RequestedPolicy = RequestedPolicy()
    dry_run: bool = True
    approval_required: bool = False
    description: str = ""
    target_environment: str = "dev"
    rollback_hint: RollbackHint = RollbackHint()


class DryRunPreview(BaseModel):
    command_preview: str
    docker_args: list[str]
    effective_policy: RequestedPolicy


class ApplyResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    oom_killed: bool = False
    timeout_killed: bool = False


class ActionResult(BaseModel):
    action_id: str
    status: Literal[
        "proposed",
        "validated",
        "dry_run",
        "approval_pending",
        "applied",
        "recorded",
        "rejected",
        "aborted",
        "failed",
    ]
    dry_run_preview: DryRunPreview | None = None
    apply_result: ApplyResult | None = None
    approval_required: bool = False
    rejection_reason: str | None = None
