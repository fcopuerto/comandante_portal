"""LDAP / Active Directory authentication for CobaltaX.

Config via environment variables (or .env):
    LDAP_HOSTS        Comma-separated DCs, e.g. "192.168.23.10,cobaltax.local"
    LDAP_PORT         389 (default) or 636 for LDAPS
    LDAP_USE_SSL      true → LDAPS on port 636 (recommended for production)
    LDAP_STARTTLS     true → StartTLS on port 389 (alternative to SSL)
    LDAP_DOMAIN       UPN suffix, e.g. "cobaltax.local"
    LDAP_BASE_DN      Search base — auto-derived from LDAP_DOMAIN if omitted
    LDAP_ADMIN_GROUP  AD group whose members get admin (default: "Domain Admins")

Most Windows Server 2019+ DCs enforce LDAP signing, so plain port-389 bind
fails with strongerAuthRequired. Use LDAP_USE_SSL=true or LDAP_STARTTLS=true.
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import ldap3
    import ldap3.core.exceptions as _ldap_exc
    _HAS_LDAP3 = True
except ImportError:
    _HAS_LDAP3 = False

# --- Config ---
_DOMAIN = os.environ.get("LDAP_DOMAIN", "").strip().lower()
_USE_SSL = os.environ.get("LDAP_USE_SSL", "").strip().lower() in ("1", "true", "yes")
_STARTTLS = os.environ.get("LDAP_STARTTLS", "").strip().lower() in ("1", "true", "yes")
_PORT = int(os.environ.get("LDAP_PORT", "636" if _USE_SSL else "389"))

# Derive base DN from domain if not explicitly set
def _derive_base_dn(domain: str) -> str:
    return ",".join(f"DC={part}" for part in domain.split("."))

_BASE_DN = os.environ.get("LDAP_BASE_DN", "").strip() or _derive_base_dn(_DOMAIN)
_ADMIN_GROUP = os.environ.get("LDAP_ADMIN_GROUP", "Domain Admins").strip()

LDAP_ENABLED = _HAS_LDAP3 and bool(os.environ.get("LDAP_HOSTS", "").strip() or _DOMAIN)


def _hosts() -> list[str]:
    raw = os.environ.get("LDAP_HOSTS", "").strip()
    if raw:
        return [h.strip() for h in raw.split(",") if h.strip()]
    # Default: try the domain name itself (DNS SRV / round-robin)
    return [_DOMAIN]


def _tls_config():
    """TLS config that skips cert validation — fine for internal AD."""
    if not (_USE_SSL or _STARTTLS):
        return None
    return ldap3.Tls(validate=ssl.CERT_NONE, version=ssl.PROTOCOL_TLS_CLIENT)


def _server_pool():
    """Build an ldap3 ServerPool that tries all configured DCs."""
    tls = _tls_config()
    servers = [
        ldap3.Server(h, port=_PORT, use_ssl=_USE_SSL, tls=tls,
                     get_info=ldap3.NONE, connect_timeout=4)
        for h in _hosts()
    ]
    if len(servers) == 1:
        return servers[0]
    return ldap3.ServerPool(servers, ldap3.ROUND_ROBIN, active=True, exhaust=True)


def authenticate(username: str, password: str) -> Tuple[bool, List[str], Optional[str]]:
    """Attempt AD authentication.

    Returns (authenticated, ad_groups, error_message).
    ad_groups is a list of CN names of groups the user belongs to.
    error_message is None on success.
    """
    if not _HAS_LDAP3:
        return False, [], "ldap3 not installed (pip install ldap3)"
    if not username or not password:
        return False, [], "Empty credentials"

    # Build UPN — accept bare username or full UPN
    upn = username if "@" in username else f"{username}@{_DOMAIN}"

    try:
        auto_bind = ldap3.AUTO_BIND_TLS_BEFORE_BIND if _STARTTLS else ldap3.AUTO_BIND_NO_TLS
        conn = ldap3.Connection(
            _server_pool(),
            user=upn,
            password=password,
            authentication=ldap3.SIMPLE,
            auto_bind=auto_bind,
            read_only=True,
            receive_timeout=5,
            raise_exceptions=False,
        )
        if not conn.bind():
            desc = (conn.result or {}).get("description", "unknown")
            return False, [], f"Invalid credentials ({desc})"

        groups = _get_user_groups(conn, upn)
        conn.unbind()
        return True, groups, None

    except Exception as exc:
        logger.warning("LDAP error for %s: %s", username, exc)
        return False, [], str(exc)


def _get_user_groups(conn: "ldap3.Connection", upn: str) -> List[str]:
    """Return list of AD group CN names the user belongs to."""
    try:
        conn.search(
            search_base=_BASE_DN,
            search_filter=f"(userPrincipalName={ldap3.utils.conv.escape_filter_chars(upn)})",
            search_scope=ldap3.SUBTREE,
            attributes=["memberOf"],
        )
        if not conn.entries:
            return []
        member_of: list[str] = conn.entries[0].memberOf.values
        groups = []
        for dn in member_of:
            # Extract CN from DN: "CN=Portal-Health-Admin,OU=Groups,DC=cobaltax,DC=local"
            cn = dn.split(",")[0].split("=", 1)[-1] if "=" in dn else dn
            groups.append(cn)
        return groups
    except Exception as exc:
        logger.warning("LDAP group fetch failed: %s", exc)
        return []
