"""LDAP auth connector — one connector for OpenLDAP and Active Directory (ADR-0020).

OpenLDAP and AD speak the same protocol; the vendor differences (user
filter, group attribute, bind DN shape) are all configuration, so there is
no per-vendor code branch. Flow is search-then-bind: bind with a read-only
service account, find the user entry, rebind as the user to verify the
password, then read the user's groups for role mapping.

Connection parameters and the service-account password come from the
environment only (ADR-0020) — never the database.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

import ldap3
from ldap3.core.exceptions import LDAPException

# (user_dn, password) → a Connection ready to .bind(). Injected in tests with
# an ldap3 MOCK_SYNC connection so the two-bind flow runs fully offline.
ConnectionFactory = Callable[[str, str], ldap3.Connection]

# Common group-membership attributes: AD uses memberOf; many OpenLDAP setups
# expose it via the memberof overlay. Both are read; whichever is present wins.
_GROUP_ATTRS_DEFAULT = "memberOf"


class LdapError(Exception):
    """LDAP bind/search failed or the connector is misconfigured."""


@dataclass(frozen=True)
class LdapConfig:
    url: str
    base_dn: str
    user_filter: str  # e.g. "(sAMAccountName={username})" or "(uid={username})"
    bind_dn: str  # read-only service account for the initial search
    bind_password: str
    group_attr: str = _GROUP_ATTRS_DEFAULT

    @classmethod
    def from_env(cls) -> LdapConfig | None:
        """Build from OPSPILOT_LDAP_* env vars; None when not configured."""
        url = os.environ.get("OPSPILOT_LDAP_URL", "")
        base_dn = os.environ.get("OPSPILOT_LDAP_BASE_DN", "")
        if not url or not base_dn:
            return None
        return cls(
            url=url,
            base_dn=base_dn,
            user_filter=os.environ.get("OPSPILOT_LDAP_USER_FILTER", "(uid={username})"),
            bind_dn=os.environ.get("OPSPILOT_LDAP_BIND_DN", ""),
            bind_password=os.environ.get("OPSPILOT_LDAP_BIND_PASSWORD", ""),
            group_attr=os.environ.get("OPSPILOT_LDAP_GROUP_ATTR", _GROUP_ATTRS_DEFAULT),
        )


@dataclass(frozen=True)
class LdapUser:
    username: str
    dn: str
    groups: list[str]


def _group_cn(dn: str) -> str:
    """'CN=IT-Admins,OU=Groups,DC=x' → 'IT-Admins'; pass through a bare name."""
    first = dn.split(",", 1)[0]
    return first.split("=", 1)[1] if "=" in first else first


class LdapConnector:
    """Search-then-bind authentication + group extraction over one directory.

    ``server_factory`` is injected in tests with an ldap3 MockSyncStrategy
    server so the whole flow runs offline; production passes None and a real
    server is built from the config URL.
    """

    def __init__(
        self, config: LdapConfig, connection_factory: ConnectionFactory | None = None
    ) -> None:
        self._cfg = config
        self._connect = connection_factory or self._real_connection

    def _real_connection(self, user: str, password: str) -> ldap3.Connection:
        server = ldap3.Server(self._cfg.url, get_info=ldap3.NONE)
        return ldap3.Connection(server, user=user, password=password)

    def _connection(self, user: str, password: str) -> ldap3.Connection:
        return self._connect(user, password)

    def test_connection(self) -> None:
        """Bind with the service account; raise LdapError on failure."""
        try:
            conn = self._connection(self._cfg.bind_dn, self._cfg.bind_password)
            if not conn.bind():
                raise LdapError(f"service-account bind failed: {conn.result}")
            conn.unbind()
        except LDAPException as exc:  # noqa: TRY003
            raise LdapError(f"LDAP connection failed: {exc}") from exc

    def authenticate(self, username: str, password: str) -> LdapUser:
        """Verify credentials and return the user's DN + group CNs.

        Raises LdapError on a service/search failure (fail-safe: the caller
        keeps local + service-token auth working) and on bad credentials.
        """
        if not password:
            raise LdapError("empty password rejected")
        try:
            search_conn = self._connection(self._cfg.bind_dn, self._cfg.bind_password)
            if not search_conn.bind():
                raise LdapError(f"service-account bind failed: {search_conn.result}")
            search_conn.search(
                search_base=self._cfg.base_dn,
                search_filter=self._cfg.user_filter.format(username=_escape(username)),
                attributes=[self._cfg.group_attr],
            )
            if not search_conn.entries:
                raise LdapError("user not found")
            entry = search_conn.entries[0]
            user_dn = entry.entry_dn
            raw_groups = entry[self._cfg.group_attr].values if self._cfg.group_attr in entry else []
            search_conn.unbind()
        except LDAPException as exc:  # noqa: TRY003
            raise LdapError(f"LDAP search failed: {exc}") from exc

        # Rebind as the user to verify the password.
        try:
            user_conn = self._connection(user_dn, password)
            if not user_conn.bind():
                raise LdapError("invalid credentials")
            user_conn.unbind()
        except LDAPException as exc:  # noqa: TRY003
            raise LdapError(f"user bind failed: {exc}") from exc

        return LdapUser(
            username=username, dn=user_dn, groups=[_group_cn(str(g)) for g in raw_groups]
        )


def _escape(value: str) -> str:
    """Escape LDAP filter metacharacters (RFC 4515) to prevent filter injection."""
    out = []
    for ch in value:
        if ch in "\\*()\0":
            out.append(f"\\{ord(ch):02x}")
        else:
            out.append(ch)
    return "".join(out)
