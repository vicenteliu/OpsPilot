"""Docker L2 hardened executor.

L2 = Docker default + --read-only rootfs + --cap-drop ALL
     + --security-opt no-new-privileges + custom seccomp profile.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .types import ActionRequest, ApplyResult, DryRunPreview

# Repo-level seccomp policy (falls back to Docker default if not found).
_SECCOMP_PROFILE = Path(__file__).parents[4] / "sandbox" / "policies" / "seccomp.template.json"
_DEFAULT_IMAGE = "alpine:3.19"


def _mem_to_docker(mem: str) -> str:
    """Convert '512Mi' → '512m', '1Gi' → '1g', etc."""
    mem = mem.strip()
    if mem.endswith("Mi"):
        return f"{mem[:-2]}m"
    if mem.endswith("Gi"):
        return f"{mem[:-2]}g"
    if mem.endswith("Ki"):
        return f"{mem[:-2]}k"
    return mem


def _build_docker_args(request: ActionRequest, image: str) -> list[str]:
    p = request.requested_policy
    workdir = p.fs.workdir
    disk = p.resource.disk_tmpfs

    args: list[str] = [
        "docker",
        "run",
        "--rm",
        "--read-only",
        f"--tmpfs={workdir}:size={disk},uid=1000",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--memory={_mem_to_docker(p.resource.memory)}",
        f"--cpus={p.resource.cpu}",
        f"--pids-limit={p.resource.pids}",
    ]

    if _SECCOMP_PROFILE.exists():
        args.append(f"--security-opt=seccomp={_SECCOMP_PROFILE}")

    if p.network.mode == "deny-all":
        args.append("--network=none")

    payload = request.payload
    shell = payload.get("shell", "/bin/sh")
    command = payload.get("command", "")
    args += [image, shell, "-c", command]

    return args


def dry_run_preview(request: ActionRequest, image: str = _DEFAULT_IMAGE) -> DryRunPreview:
    args = _build_docker_args(request, image)
    # Redact absolute seccomp path in the preview.
    safe_args = [
        "--security-opt=seccomp=<profile>"
        if "seccomp=" in a and a != "--security-opt=no-new-privileges"
        else a
        for a in args
    ]
    preview = "[dry-run] " + " ".join(safe_args[:12])
    if len(safe_args) > 12:
        preview += " ..."
    return DryRunPreview(
        command_preview=preview,
        docker_args=safe_args,
        effective_policy=request.requested_policy,
    )


def run_l2(request: ActionRequest, image: str = _DEFAULT_IMAGE) -> ApplyResult:
    args = _build_docker_args(request, image)
    timeout = request.requested_policy.resource.timeout_seconds
    start = time.monotonic()
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        duration_ms = int((time.monotonic() - start) * 1000)
        return ApplyResult(
            exit_code=proc.returncode,
            stdout=proc.stdout[:8192],
            stderr=proc.stderr[:8192],
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - start) * 1000)
        return ApplyResult(
            exit_code=-1,
            stdout="",
            stderr="[sandbox] timeout expired",
            duration_ms=duration_ms,
            timeout_killed=True,
        )
    except FileNotFoundError:
        return ApplyResult(
            exit_code=-1,
            stdout="",
            stderr="[sandbox] docker not found — install Docker to use apply mode",
            duration_ms=0,
        )
