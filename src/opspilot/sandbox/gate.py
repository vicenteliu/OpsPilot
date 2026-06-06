"""Approval gate — flags whether an action should get human sign-off.

This is a **defense-in-depth signal and audit aid, not a security boundary**
(see ADR-0005). The real boundary is the Docker L2 hardened container plus the
network policy. The denylist below is best-effort: it catches common dangerous
shapes so the operator is prompted, but a determined caller can phrase a command
to evade it — that is acceptable because filesystem blast radius is contained by
the ephemeral read-only container, and network side effects are gated separately
(opening the network forces approval).
"""

from __future__ import annotations

import re

from .types import ActionRequest

_DANGEROUS_PATTERNS = [
    r"rm\s+--no-preserve-root",
    r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b",
    r"\bTRUNCATE\b",
    r"\bDELETE\s+FROM\b",  # unqualified deletes look the same as scoped
    r"chmod\s+[0-7]*7[0-7][0-7]",  # chmod 777 / 0777
    r":\(\)\s*\{[^}]*\}\s*;",  # fork bomb
    r"\bfind\b[^|;&]*\s-delete\b",  # find ... -delete
    r"\bdd\b[^|;&]*\bof=",  # dd of=/dev/...
    r"\bmkfs(\.\w+)?\b",  # mkfs / mkfs.ext4
    r">\s*/dev/(sd|nvme|hd|disk|vd)\w*",  # clobber a raw disk
    r"\bgit\s+push\b[^|;&]*--force\b",
    r"\bkubectl\s+delete\b",
]

# Recursive + force `rm` in any order / spelling, including split flags
# (`rm -r -f`, `rm -fr`, `rm --recursive --force`) which a single combined-flag
# regex misses.
_RM_RECURSIVE = re.compile(r"\brm\b[^|;&]*?(?:-\w*[rR]\w*|--recursive)\b")
_RM_FORCE = re.compile(r"\brm\b[^|;&]*?(?:-\w*f\w*|--force)\b")

_PROD_ENVS = {"prod", "production"}


def _command_is_dangerous(cmd: str) -> bool:
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True
    return bool(_RM_RECURSIVE.search(cmd) and _RM_FORCE.search(cmd))


def check_approval_required(request: ActionRequest) -> bool:
    """Return True if the action should pass an approval gate before apply."""
    if request.target_environment in _PROD_ENVS:
        return True
    if request.rollback_hint.irreversible:
        return True
    # Any non-isolated network reaches real systems — the container can no
    # longer contain side effects, so require sign-off regardless of command.
    if request.requested_policy.network.mode != "deny-all":
        return True
    if request.type in ("shell", "script"):
        cmd = str(request.payload.get("command", ""))
        if _command_is_dangerous(cmd):
            return True
    return False
