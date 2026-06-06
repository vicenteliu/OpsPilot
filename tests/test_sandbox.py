"""Tests for Sandbox L2 — gate, dry-run, and docker args (PR-30).

No Docker required: apply-path tests are excluded. Gate and dry-run logic
is fully deterministic and runs without external services.
"""

from __future__ import annotations

import pytest

from opspilot.sandbox.docker_l2 import _build_docker_args
from opspilot.sandbox.engine import SandboxEngine
from opspilot.sandbox.gate import check_approval_required
from opspilot.sandbox.types import (
    ActionRequest,
    NetworkPolicy,
    RequestedPolicy,
    RollbackHint,
)


def _req(**kwargs) -> ActionRequest:
    defaults: dict = {
        "id": "act_01TEST000000000000000000000",
        "session_id": "sess_01TEST000000000000000000000",
        "proposed_by": "user:test",
        "created_at": "2026-05-05T00:00:00Z",
        "type": "shell",
        "payload": {"command": "uptime", "shell": "/bin/sh"},
    }
    defaults.update(kwargs)
    return ActionRequest(**defaults)


# ── Gate ──────────────────────────────────────────────────────────────────


def test_gate_safe_command_passes():
    assert not check_approval_required(_req())


def test_gate_rm_rf_triggers():
    assert check_approval_required(_req(payload={"command": "rm -rf /tmp/test"}))


def test_gate_rm_fr_triggers():
    assert check_approval_required(_req(payload={"command": "rm -fr /tmp/test"}))


def test_gate_prod_env_triggers():
    assert check_approval_required(_req(target_environment="prod"))


def test_gate_production_env_triggers():
    assert check_approval_required(_req(target_environment="production"))


def test_gate_irreversible_triggers():
    assert check_approval_required(_req(rollback_hint=RollbackHint(irreversible=True)))


def test_gate_truncate_triggers():
    assert check_approval_required(
        _req(payload={"command": "echo 'TRUNCATE TABLE sessions' | mysql"})
    )


def test_gate_drop_table_triggers():
    assert check_approval_required(_req(payload={"command": "psql -c 'DROP TABLE users'"}))


def test_gate_dev_env_passes():
    assert not check_approval_required(_req(target_environment="dev"))


# ── Gate: previously-bypassable denylist patterns (ADR-0005 signal patches) ──


@pytest.mark.parametrize(
    "command",
    [
        "rm -r -f /tmp/x",  # split recursive/force flags
        "rm --recursive --force /x",
        "rm -f -r /tmp/x",  # reversed split flags
        "find / -name '*.log' -delete",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sdb1",
        "cat payload > /dev/sda",
        "git push --force origin main",
        "kubectl delete namespace prod",
        "psql -c 'DELETE FROM users'",
    ],
)
def test_gate_catches_dangerous_variants(command: str):
    assert check_approval_required(_req(payload={"command": command}))


def test_gate_plain_rm_without_force_passes():
    # Recursive-only or force-only (not both) is not treated as catastrophic.
    assert not check_approval_required(_req(payload={"command": "rm -r /tmp/scratch"}))
    assert not check_approval_required(_req(payload={"command": "rm -f /tmp/one"}))


# ── Gate: opening the network forces approval ────────────────────────────────


def test_gate_network_open_triggers():
    pol = RequestedPolicy(network=NetworkPolicy(mode="open"))
    assert check_approval_required(_req(requested_policy=pol))


def test_gate_network_allowlist_triggers():
    pol = RequestedPolicy(network=NetworkPolicy(mode="allowlist"))
    assert check_approval_required(_req(requested_policy=pol))


def test_gate_network_deny_all_safe_command_passes():
    pol = RequestedPolicy(network=NetworkPolicy(mode="deny-all"))
    assert not check_approval_required(_req(requested_policy=pol))


# ── Docker args ───────────────────────────────────────────────────────────


def test_docker_args_l2_flags():
    args = _build_docker_args(_req(), "alpine:3.19")
    flat = " ".join(args)
    assert "--read-only" in flat
    assert "--cap-drop=ALL" in flat
    assert "--security-opt=no-new-privileges" in flat
    assert "--network=none" in flat


def test_docker_args_resource_limits():
    args = _build_docker_args(_req(), "alpine:3.19")
    flat = " ".join(args)
    assert "--memory=" in flat
    assert "--cpus=" in flat
    assert "--pids-limit=" in flat


def test_docker_args_tmpfs_uses_workdir():
    args = _build_docker_args(_req(), "alpine:3.19")
    tmpfs_args = [a for a in args if a.startswith("--tmpfs=")]
    assert len(tmpfs_args) == 1
    assert "/work" in tmpfs_args[0]


# ── Engine dry-run ────────────────────────────────────────────────────────


def test_engine_dry_run_returns_dry_run_status():
    result = SandboxEngine().dry_run(_req())
    assert result.status == "dry_run"


def test_engine_dry_run_has_preview():
    result = SandboxEngine().dry_run(_req())
    assert result.dry_run_preview is not None
    assert "dry-run" in result.dry_run_preview.command_preview


def test_engine_dry_run_no_approval_for_safe():
    result = SandboxEngine().dry_run(_req())
    assert not result.approval_required


def test_engine_dry_run_flags_approval_for_dangerous():
    req = _req(payload={"command": "rm -rf /work"})
    result = SandboxEngine().dry_run(req)
    assert result.status == "dry_run"  # still returns preview
    assert result.approval_required  # but flags it


def test_engine_execute_dry_run_flag():
    req = _req(dry_run=True)
    result = SandboxEngine().execute(req)
    assert result.status == "dry_run"


def test_engine_execute_blocks_dangerous_without_approve():
    req = _req(payload={"command": "rm -rf /work"}, dry_run=False)
    result = SandboxEngine().execute(req)
    assert result.status == "approval_pending"
    assert result.rejection_reason is not None
