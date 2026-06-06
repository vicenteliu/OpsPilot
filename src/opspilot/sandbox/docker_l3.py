"""Docker L3 executor — gVisor (runsc) strong isolation (ADR-0009).

L3 = the full L2 hardened surface (read-only rootfs, cap-drop ALL,
no-new-privileges, seccomp, resource limits, deny-all network) **plus** the
gVisor user-space kernel via Docker's `--runtime=runsc`. The container no longer
shares the host Linux kernel's syscall surface directly; runsc intercepts and
re-implements syscalls, raising the bar from "container escape needs a kernel
0-day" toward microVM-class isolation.

Fail-closed: if `runsc` is not registered with the Docker daemon, L3 refuses to
run rather than silently downgrading to L2. A weaker boundary than the operator
asked for is a security regression, not a graceful fallback.
"""

from __future__ import annotations

import subprocess

from .docker_l2 import _DEFAULT_IMAGE, _build_docker_args, _exec_docker
from .types import ActionRequest, ApplyResult

_RUNSC_RUNTIME = "runsc"


def runsc_available() -> bool:
    """True if the Docker daemon has the gVisor `runsc` runtime registered."""
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{json .Runtimes}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and _RUNSC_RUNTIME in proc.stdout


def run_l3(request: ActionRequest, image: str = _DEFAULT_IMAGE) -> ApplyResult:
    if not runsc_available():
        return ApplyResult(
            exit_code=-1,
            stdout="",
            stderr=(
                "[sandbox] L3 requested but the gVisor runtime 'runsc' is not "
                "registered with Docker — refusing to fall back to L2 "
                "(fail-closed). Install runsc and register it in "
                "/etc/docker/daemon.json. See sandbox/backends/README.md §3."
            ),
            duration_ms=0,
        )
    args = _build_docker_args(request, image, runtime=_RUNSC_RUNTIME)
    return _exec_docker(args, request.requested_policy.resource.timeout_seconds)
