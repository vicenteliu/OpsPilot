"""Approval gate — checks whether an action requires human sign-off."""

from __future__ import annotations

import re

from .types import ActionRequest

_DANGEROUS_PATTERNS = [
    r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b",  # rm -rf / rm -fr
    r"rm\s+--no-preserve-root",
    r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b",
    r"\bTRUNCATE\b",
    r"chmod\s+[0-7]*7[0-7][0-7]",   # chmod 777 / 0777
    r":\(\)\s*\{[^}]*\}\s*;",       # fork bomb
]

_PROD_ENVS = {"prod", "production"}


def check_approval_required(request: ActionRequest) -> bool:
    """Return True if the action must pass an approval gate before apply."""
    if request.target_environment in _PROD_ENVS:
        return True
    if request.rollback_hint.irreversible:
        return True
    if request.type in ("shell", "script"):
        cmd = str(request.payload.get("command", ""))
        for pattern in _DANGEROUS_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True
    return False
