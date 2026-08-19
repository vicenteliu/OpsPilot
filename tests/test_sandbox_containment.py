"""The sandbox is the boundary, so something has to actually run in it.

ADR-0005 makes the sandbox the real boundary — the approval gate is an admitted
heuristic denylist and says so in its own docstring. Every other sandbox test
asserts on the argv we hand `docker`, and argv is a claim, not a control.

Two defects lived their whole life behind that gap. `--tmpfs=…size=64Mi` is a
Kubernetes quantity the kernel rejects, so no container ever started (#209). And
the seccomp policy path pointed one level above the repo root at a directory
that has never existed, so the profile was never applied — and when the path was
fixed, the profile turned out to deny `clone`, which is how libc implements
fork, so nothing could start at all.

**What these cannot tell you**: whether *our* profile is loaded or Docker's
default is. Both deny the things probed below, so the containment assertions
pass either way — `test_the_seccomp_policy_is_where_the_code_looks_for_it`
covers that gap, because it is the half that broke.

Marked `requires_docker` and excluded from the default run: it needs a daemon
and the `alpine:3.19` image. It is worth running whenever the argv, the policy,
or the profile changes.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from opspilot.sandbox.docker_l2 import _DEFAULT_IMAGE, _SECCOMP_PROFILE
from opspilot.sandbox.engine import SandboxEngine
from opspilot.sandbox.proposals import to_request

pytestmark = pytest.mark.requires_docker


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "image", "inspect", _DEFAULT_IMAGE], capture_output=True, check=True
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    return True


needs_docker = pytest.mark.skipif(
    not _docker_ready(), reason=f"needs a docker daemon and the {_DEFAULT_IMAGE} image"
)


def _run(command: str) -> tuple[str, str, int]:
    """Execute *command* through the real engine, exactly as a proposal would."""
    request = to_request(
        {
            "ref": "pa-1",
            "intent": "diagnose",
            "type": "shell",
            "command": command,
            "target": "sandbox-self",
            "why": "verifying the declared controls are in effect",
        },
        session_id="sess_containment",
        proposed_by="test",
    )
    result = SandboxEngine().execute(
        request.model_copy(update={"dry_run": False}), force_approve=True
    )
    assert result.apply_result is not None
    return result.apply_result.stdout, result.apply_result.stderr, result.apply_result.exit_code


def test_the_seccomp_policy_is_where_the_code_looks_for_it() -> None:
    """No docker needed, and the one assertion the rest cannot make.

    `_SECCOMP_PROFILE` is applied behind `if …exists()`, so a wrong path is not
    an error — it is a silent fallback to Docker's default, which denies enough
    of the same things that every containment probe still passes. The path was
    wrong from PR-30 until 2026-08-19: one level above the repo root, pointing
    at a `sandbox/policies/` directory that has never existed.
    """
    assert _SECCOMP_PROFILE.is_file(), f"the profile is not at {_SECCOMP_PROFILE}"
    policy = json.loads(_SECCOMP_PROFILE.read_text())
    assert policy["defaultAction"] == "SCMP_ACT_ERRNO", "the allowlist must deny by default"
    allowed = {
        n
        for rule in policy["syscalls"]
        if rule["action"] == "SCMP_ACT_ALLOW"
        for n in rule["names"]
    }
    # libc implements fork() with clone; `fork` alone does not exist on aarch64.
    assert "clone" in allowed, "nothing can start a process without clone"


@needs_docker
def test_a_container_starts_and_reports_its_output() -> None:
    """The floor: without this the other assertions are vacuous."""
    stdout, _, exit_code = _run("echo alive")
    assert exit_code == 0
    assert "alive" in stdout


@needs_docker
def test_a_subprocess_can_be_created() -> None:
    """A profile denying `clone` fails here and nowhere else.

    `fork` and `vfork` being on an allowlist is not enough: libc implements
    fork() with `clone`, and on aarch64 the `fork` syscall does not exist.
    """
    stdout, stderr, exit_code = _run("echo one | cat")
    assert "can't fork" not in stderr
    assert exit_code == 0
    assert "one" in stdout


@needs_docker
def test_the_process_holds_no_capabilities() -> None:
    stdout, _, _ = _run("grep -E '^(CapEff|CapBnd):' /proc/self/status")
    caps = dict(re.findall(r"^(CapEff|CapBnd):\s*(\w+)", stdout, re.M))
    assert caps.get("CapEff") == "0000000000000000", stdout
    # The bounding set too, or a setuid binary could regain them.
    assert caps.get("CapBnd") == "0000000000000000", stdout


@needs_docker
def test_privileges_cannot_be_regained() -> None:
    stdout, _, _ = _run("grep -E '^(NoNewPrivs|Seccomp):' /proc/self/status")
    assert re.search(r"^NoNewPrivs:\s*1", stdout, re.M), stdout
    # 2 = a seccomp filter is loaded. 0 would mean the profile silently vanished.
    assert re.search(r"^Seccomp:\s*2", stdout, re.M), stdout


@needs_docker
def test_the_root_filesystem_is_read_only() -> None:
    stdout, _, _ = _run("touch /etc/probe 2>/dev/null && echo WRITABLE || echo blocked")
    assert "blocked" in stdout, stdout


@needs_docker
def test_the_workdir_is_writable_but_capped() -> None:
    stdout, _, _ = _run(
        "dd if=/dev/zero of=/work/big bs=1M count=80 2>/dev/null; wc -c < /work/big"
    )
    written = int(stdout.strip().split()[-1])
    assert written == 64 * 1024 * 1024, f"tmpfs cap not enforced: wrote {written} bytes"


@needs_docker
def test_there_is_no_network() -> None:
    stdout, _, _ = _run(
        "ip -o addr 2>/dev/null | awk '{print $2}' | sort -u; echo ---; ip route 2>/dev/null | wc -l"
    )
    interfaces, _, routes = stdout.partition("---")
    assert set(interfaces.split()) <= {"lo"}, f"an addressed interface besides lo: {interfaces}"
    assert routes.strip() == "0", f"a route exists: {routes}"


@needs_docker
@pytest.mark.parametrize(
    ("label", "command"),
    [
        ("new user namespace", "unshare -U true"),
        ("new network namespace", "unshare -n true"),
        ("chroot", "chroot /tmp /bin/true"),
        ("mount", "mount -t tmpfs none /work"),
    ],
)
def test_the_profile_denies_what_it_claims_to(label: str, command: str) -> None:
    """Deny-by-default is the point of the allowlist; check it bites."""
    _, stderr, exit_code = _run(f"{command} 2>&1")
    assert exit_code != 0, f"{label} succeeded"
