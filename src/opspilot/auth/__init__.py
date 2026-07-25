"""Multi-user authentication and authorization (ADR-0020)."""

from .deps import COOKIE_NAME, Identity, current_identity, require_role
from .store import ROLES, AuthStore, hash_password, role_at_least, verify_password

__all__ = [
    "COOKIE_NAME",
    "ROLES",
    "AuthStore",
    "Identity",
    "current_identity",
    "hash_password",
    "require_role",
    "role_at_least",
    "verify_password",
]
