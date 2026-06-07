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


def _build_docker_args(request: ActionRequest, image: str, runtime: str | None = None) -> list[str]:
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

    # L3 selects an alternate OCI runtime (gVisor's runsc). The hardening flags
    # above are unchanged — L3 = L2 surface + a stronger isolation boundary.
    if runtime:
        args.insert(2, f"--runtime={runtime}")

    if _SECCOMP_PROFILE.exists():
        args.append(f"--security-opt=seccomp={_SECCOMP_PROFILE}")

    if p.network.mode == "deny-all":
        args.append("--network=none")

    payload = request.payload
    shell = payload.get("shell", "/bin/sh")
    command = payload.get("command", "")
    args += [image, shell, "-c", command]

    return args


def dry_run_preview(
    request: ActionRequest, image: str = _DEFAULT_IMAGE, runtime: str | None = None
) -> DryRunPreview:
    args = _build_docker_args(request, image, runtime)
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


def _exec_docker(args: list[str], timeout: int) -> ApplyResult:
    """Run a prepared `docker run ...` argv and map it to an ApplyResult.

    Shared by L2 and L3 — the only difference between the levels is the argv
    (L3 adds `--runtime=runsc`), not the execution or result mapping.
    """
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


def run_l2(request: ActionRequest, image: str = _DEFAULT_IMAGE) -> ApplyResult:
    args = _build_docker_args(request, image)
    return _exec_docker(args, request.requested_policy.resource.timeout_seconds)
