"""CobaltaX config store — MSSQL backend.

Tables (all prefixed cobaltax_ to coexist with support tables):
  cobaltax_servers      server list + SSH credentials
  cobaltax_auth_users   application users + hashed/encrypted passwords
  cobaltax_settings     key-value store for Telegram creds and other settings

Passwords are Fernet-encrypted at rest. The symmetric key is read from:
  1. CONFIG_MASTER_KEY  env var (base64 Fernet key)
  2. ~/.cobaltax/.config_master.key  file (created automatically on first run)

Connection: see db.py (MSSQL_SERVER / MSSQL_DATABASE / MSSQL_USER / MSSQL_PASSWORD).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from db import get_conn

try:
    from cryptography.fernet import Fernet
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

_KEY_ENV  = "CONFIG_MASTER_KEY"
_KEY_FILE = os.path.join(os.path.expanduser("~"), ".cobaltax", ".config_master.key")


# ── Encryption ────────────────────────────────────────────────────────────────

def _ensure_key() -> Optional[bytes]:
    if not _HAS_CRYPTO:
        return None
    key = os.environ.get(_KEY_ENV)
    if key:
        return key.encode() if isinstance(key, str) else key
    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            key = f.read().strip()
        os.environ[_KEY_ENV] = key.decode()
        return key
    key = Fernet.generate_key()
    os.makedirs(os.path.dirname(_KEY_FILE), exist_ok=True)
    with open(_KEY_FILE, "wb") as f:
        f.write(key)
    try:
        os.chmod(_KEY_FILE, 0o600)
    except OSError:
        pass
    os.environ[_KEY_ENV] = key.decode()
    return key


def _cipher():
    if not _HAS_CRYPTO:
        return None
    key = _ensure_key()
    return Fernet(key) if key else None


def _encrypt(plain: Optional[str]) -> Optional[bytes]:
    if plain is None:
        return None
    c = _cipher()
    return c.encrypt(plain.encode()) if c else plain.encode()


def _decrypt(blob: Optional[bytes]) -> Optional[str]:
    if blob is None:
        return None
    c = _cipher()
    try:
        return c.decrypt(bytes(blob)).decode() if c else bytes(blob).decode()
    except Exception:
        return None


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db(migrate: bool = True) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            IF OBJECT_ID('cobaltax_servers', 'U') IS NULL
            BEGIN
                CREATE TABLE cobaltax_servers (
                    id              INT             IDENTITY(1,1) PRIMARY KEY,
                    name            NVARCHAR(200)   NOT NULL,
                    ip              NVARCHAR(50)    NOT NULL UNIQUE,
                    ssh_user        NVARCHAR(100),
                    ssh_password_enc VARBINARY(MAX),
                    ssh_port        INT             NOT NULL DEFAULT 22,
                    os_type         NVARCHAR(50)    NOT NULL DEFAULT 'linux',
                    parent_ip       NVARCHAR(50),
                    ssh_key_path    NVARCHAR(500),
                    watts_idle      FLOAT,
                    watts_max       FLOAT,
                    subnet          NVARCHAR(100),
                    web_url         NVARCHAR(500)
                )
            END
        """)
        cur.execute("""
            IF OBJECT_ID('cobaltax_auth_users', 'U') IS NULL
            BEGIN
                CREATE TABLE cobaltax_auth_users (
                    id              INT             IDENTITY(1,1) PRIMARY KEY,
                    username        NVARCHAR(200)   NOT NULL UNIQUE,
                    password_enc    VARBINARY(MAX),
                    is_admin        BIT             NOT NULL DEFAULT 0
                )
            END
        """)
        cur.execute("""
            IF OBJECT_ID('cobaltax_settings', 'U') IS NULL
            BEGIN
                CREATE TABLE cobaltax_settings (
                    [key]       NVARCHAR(200)   NOT NULL PRIMARY KEY,
                    value_enc   VARBINARY(MAX),
                    is_secret   BIT             NOT NULL DEFAULT 1
                )
            END
        """)
    if migrate:
        _maybe_migrate_from_config()
        _maybe_migrate_env_settings()


# ── Migration from config.py defaults ─────────────────────────────────────────

def _maybe_migrate_from_config() -> None:
    try:
        from config import SERVERS, AUTH_USERS, AUTH_PASSWORDS, ADMIN_USERS
    except Exception:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM cobaltax_servers")
        if cur.fetchone()[0] == 0:
            for s in SERVERS:
                pwd = s.get("ssh_password") or (
                    os.environ.get(s["ssh_password_env"])
                    if s.get("ssh_password_env") else None
                )
                _upsert_server_cur(cur, s, pwd)
        cur.execute("SELECT COUNT(*) FROM cobaltax_auth_users")
        if cur.fetchone()[0] == 0:
            for u in AUTH_USERS:
                pwd = AUTH_PASSWORDS.get(u)
                enc = _encrypt(pwd)
                adm = 1 if u in ADMIN_USERS else 0
                cur.execute(
                    "INSERT INTO cobaltax_auth_users (username, password_enc, is_admin) VALUES (?,?,?)",
                    u, enc, adm,
                )


_SECRET_PATTERNS = ("PASS", "HASH", "KEY", "SECRET", "TOKEN", "PASSWORD", "API_ID", "CHAT_ID")

_ENV_KEYS_TO_MIGRATE = [
    # Telegram
    "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_CHAT_ID",
    "TELEGRAM_DEFAULT_LIMIT", "TELEGRAM_REFRESH_INTERVAL",
    # Auth
    "COBALTAX_USERS", "COBALTAX_PASS", "COBALTAX_ADMINS", "COBALTAX_USER",
    # LDAP
    "LDAP_HOSTS", "LDAP_DOMAIN", "LDAP_BASE_DN", "LDAP_ADMIN_GROUP",
    "LDAP_PORT", "LDAP_USE_SSL", "LDAP_STARTTLS",
    # AI
    "AI_API_KEY",
    # SSH timeouts
    "SSH_BANNER_TIMEOUT", "SSH_AUTH_TIMEOUT",
]


def _maybe_migrate_env_settings() -> None:
    keys = list(_ENV_KEYS_TO_MIGRATE)
    # Dynamically include per-user passwords COBALTAX_PASS_*
    keys += [k for k in os.environ if k.startswith("COBALTAX_PASS_")]
    # Dynamically include per-server SSH passwords SSH_PASS_*
    keys += [k for k in os.environ if k.startswith("SSH_PASS_")]
    for k in keys:
        val = os.environ.get(k)
        if val and get_setting(k) is None:
            secret = any(p in k for p in _SECRET_PATTERNS)
            set_setting(k, val, secret=secret)


# ── Servers ───────────────────────────────────────────────────────────────────

def _upsert_server_cur(cur, s: Dict[str, Any], pwd: Optional[str] = None) -> None:
    enc = _encrypt(pwd)
    ip = s.get("ip")
    cur.execute("SELECT 1 FROM cobaltax_servers WHERE ip=?", ip)
    if cur.fetchone():
        cur.execute("""
            UPDATE cobaltax_servers SET
                name=?, ssh_user=?,
                ssh_password_enc=COALESCE(?, ssh_password_enc),
                ssh_port=?, os_type=?, parent_ip=?, ssh_key_path=?,
                watts_idle=?, watts_max=?, subnet=?, web_url=?
            WHERE ip=?
        """,
            s.get("name"), s.get("ssh_user"), enc,
            int(s.get("ssh_port") or 22), s.get("os_type", "linux"),
            s.get("parent"), s.get("ssh_key_path"),
            s.get("watts_idle"), s.get("watts_max"), s.get("subnet"), s.get("web_url"),
            ip,
        )
    else:
        cur.execute("""
            INSERT INTO cobaltax_servers
                (name, ip, ssh_user, ssh_password_enc, ssh_port, os_type,
                 parent_ip, ssh_key_path, watts_idle, watts_max, subnet, web_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            s.get("name"), ip, s.get("ssh_user"), enc,
            int(s.get("ssh_port") or 22), s.get("os_type", "linux"),
            s.get("parent"), s.get("ssh_key_path"),
            s.get("watts_idle"), s.get("watts_max"), s.get("subnet"), s.get("web_url"),
        )


def load_servers() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT name, ip, ssh_user, ssh_password_enc, ssh_port, os_type,
                   parent_ip, ssh_key_path, watts_idle, watts_max, subnet, web_url
            FROM cobaltax_servers ORDER BY id
        """)
        rows = cur.fetchall()
    return [
        {
            "name": r[0], "ip": r[1], "ssh_user": r[2],
            "ssh_password": _decrypt(r[3]),
            "ssh_password_env": None,
            "ssh_port": r[4], "os_type": r[5],
            "parent": r[6], "ssh_key_path": r[7],
            "watts_idle": r[8], "watts_max": r[9],
            "subnet": r[10], "web_url": r[11],
        }
        for r in rows
    ]


def upsert_server(server: Dict[str, Any]) -> None:
    pwd = server.get("ssh_password")
    with get_conn() as conn:
        _upsert_server_cur(conn.cursor(), server, pwd)


def delete_server(ip: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM cobaltax_servers WHERE ip=?", ip)
        return cur.rowcount > 0


# ── Auth users ────────────────────────────────────────────────────────────────

def get_user_password(username: str) -> Optional[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT password_enc FROM cobaltax_auth_users WHERE username=?", username
        )
        row = cur.fetchone()
    return _decrypt(row[0]) if row and row[0] else None


def list_users() -> List[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT username FROM cobaltax_auth_users ORDER BY username")
        return [r[0] for r in cur.fetchall()]


def is_admin(username: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT is_admin FROM cobaltax_auth_users WHERE username=?", username
        )
        row = cur.fetchone()
    return bool(row and row[0])


def upsert_user(username: str, password: Optional[str], is_admin_flag: bool = False) -> None:
    enc = _encrypt(password)
    adm = 1 if is_admin_flag else 0
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM cobaltax_auth_users WHERE username=?", username)
        if cur.fetchone():
            cur.execute(
                "UPDATE cobaltax_auth_users SET password_enc=COALESCE(?,password_enc), is_admin=? WHERE username=?",
                enc, adm, username,
            )
        else:
            cur.execute(
                "INSERT INTO cobaltax_auth_users (username, password_enc, is_admin) VALUES (?,?,?)",
                username, enc, adm,
            )


# ── Settings ──────────────────────────────────────────────────────────────────

def inject_settings_to_env() -> int:
    """Load all cobaltax_settings into os.environ (skip keys already set).

    Call this in main.py before importing web_app so that config.py and
    ldap_auth.py — which read os.environ at module-import time — see the
    values stored in SQL Server.

    Returns the number of settings injected.
    """
    try:
        injected = 0
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT [key], value_enc FROM cobaltax_settings")
            rows = cur.fetchall()
        for key, blob in rows:
            if key not in os.environ and blob:
                val = _decrypt(blob)
                if val is not None:
                    os.environ[key] = val
                    injected += 1
        return injected
    except Exception as e:
        print(f"[secure_config_store] inject_settings_to_env failed: {e}")
        return 0


def get_setting(key: str) -> Optional[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value_enc FROM cobaltax_settings WHERE [key]=?", key)
        row = cur.fetchone()
    return _decrypt(row[0]) if row and row[0] else None


def set_setting(key: str, value: Optional[str], secret: bool = True) -> None:
    if value is None:
        return
    enc = _encrypt(value)
    isc = 1 if secret else 0
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM cobaltax_settings WHERE [key]=?", key)
        if cur.fetchone():
            cur.execute(
                "UPDATE cobaltax_settings SET value_enc=?, is_secret=? WHERE [key]=?",
                enc, isc, key,
            )
        else:
            cur.execute(
                "INSERT INTO cobaltax_settings ([key], value_enc, is_secret) VALUES (?,?,?)",
                key, enc, isc,
            )


# Auto-init when imported (same behaviour as before)
if os.environ.get("COBALTAX_SECURE_STORE_AUTO_INIT", "1") == "1":
    try:
        init_db(migrate=True)
    except Exception as _e:
        print(f"[secure_config_store] init warning: {_e}")
