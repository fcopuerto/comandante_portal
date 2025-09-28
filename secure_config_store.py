"""Secure configuration storage using SQLite + symmetric encryption.

This module migrates existing in-memory configuration (servers + auth users)
from `config.py` into a local SQLite database (`config_store.sqlite` by
default) and encrypts sensitive passwords using a Fernet key.

Key management strategy (simple, local-first):

1. If environment variable CONFIG_MASTER_KEY is set (base64 32-byte Fernet key)
   it is used directly.
2. Else, if a local file `.config_master.key` exists, its contents are used.
3. Else, a new Fernet key is generated, stored in `.config_master.key` with
   permission 600, and used.

NOTE: This is a pragmatic local protection model (protects at-rest secrets
against casual inspection). For stronger security, derive key from a user
passphrase (PBKDF2/Argon2) prompted at runtime and never store the raw key.

Schema:
  servers(
      id INTEGER PK,
      name TEXT,
      ip TEXT UNIQUE,
      ssh_user TEXT,
      ssh_password_enc BLOB NULL,
      ssh_port INTEGER,
      os_type TEXT,
      parent_ip TEXT NULL,
      ssh_key_path TEXT NULL
  )

  auth_users(
      id INTEGER PK,
      username TEXT UNIQUE,
      password_enc BLOB NULL,
      is_admin INTEGER DEFAULT 0
  )

We store encrypted (reversible) values because the existing login dialog
compares plaintext passwords. If desired, migration to salted hashing is
straightforward (store hash + random salt instead of ciphertext).
"""

from __future__ import annotations

import os
import sqlite3
import base64
from typing import List, Dict, Optional, Tuple, Any
import json
import threading

try:
    from cryptography.fernet import Fernet
    _HAS_CRYPTO = True
except Exception:  # cryptography not installed yet
    _HAS_CRYPTO = False

DB_PATH = os.environ.get('COBALTAX_CONFIG_DB', 'config_store.sqlite')
KEY_FILE = '.config_master.key'
KEY_ENV = 'CONFIG_MASTER_KEY'
CACHE_PATH = os.environ.get('COBALTAX_CONFIG_CACHE', 'config_cache.json')

_CACHE_LOCK = threading.Lock()


# ------------- Cache Helpers -------------
def _cache_write(servers: List[Dict[str, Any]], users: List[Tuple[str, Optional[str], bool]]):
    """Persist a cache copy so we can operate if the DB becomes unavailable.

    Passwords are re-encrypted (ciphertext base64) if encryption available; else
    they are stored in plaintext (last resort)."""
    try:
        cipher = _get_cipher()
        ser_servers = []
        for s in servers:
            pwd = s.get('ssh_password')
            if pwd and cipher:
                try:
                    enc = cipher.encrypt(pwd.encode('utf-8')).decode('utf-8')
                except Exception:
                    enc = pwd
            else:
                enc = pwd
            ser_servers.append({
                'name': s.get('name'), 'ip': s.get('ip'), 'ssh_user': s.get('ssh_user'),
                'ssh_password': enc, 'ssh_port': s.get('ssh_port', 22), 'os_type': s.get('os_type', 'linux'),
                'parent': s.get('parent'), 'ssh_key_path': s.get('ssh_key_path'), 'enc': bool(cipher)
            })
        ser_users = []
        for u, pw, is_admin in users:
            if pw and cipher:
                try:
                    enc_pw = cipher.encrypt(pw.encode('utf-8')).decode('utf-8')
                except Exception:
                    enc_pw = pw
            else:
                enc_pw = pw
            ser_users.append({'username': u, 'password': enc_pw,
                             'is_admin': is_admin, 'enc': bool(cipher)})
        payload = {'version': 1, 'servers': ser_servers, 'users': ser_users}
        with _CACHE_LOCK:
            with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:  # pragma: no cover - best effort
        print(f"[secure_config_store] cache write failed: {e}")


def _cache_load() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Return (servers, users_map) from cache or ([],{})."""
    try:
        if not os.path.exists(CACHE_PATH):
            return [], {}
        with _CACHE_LOCK:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
        cipher = _get_cipher()
        servers: List[Dict[str, Any]] = []
        for s in data.get('servers', []):
            pwd = s.get('ssh_password')
            if pwd and s.get('enc') and cipher:
                try:
                    pwd = cipher.decrypt(pwd.encode('utf-8')).decode('utf-8')
                except Exception:
                    pass
            servers.append({
                'name': s.get('name'), 'ip': s.get('ip'), 'ssh_user': s.get('ssh_user'),
                'ssh_password': pwd, 'ssh_password_env': None, 'ssh_port': s.get('ssh_port', 22),
                'os_type': s.get('os_type', 'linux'), 'parent': s.get('parent'), 'ssh_key_path': s.get('ssh_key_path')
            })
        users_map: Dict[str, Dict[str, Any]] = {}
        for u in data.get('users', []):
            pw = u.get('password')
            if pw and u.get('enc') and cipher:
                try:
                    pw = cipher.decrypt(pw.encode('utf-8')).decode('utf-8')
                except Exception:
                    pass
            users_map[u.get('username')] = {
                'password': pw, 'is_admin': bool(u.get('is_admin'))}
        return servers, users_map
    except Exception as e:  # pragma: no cover
        print(f"[secure_config_store] cache load failed: {e}")
        return [], {}


# ------------- Encryption Helpers -------------
def _ensure_key() -> Optional[bytes]:
    """Return (and create if needed) the Fernet key bytes.

    If cryptography isn't installed we return None (plaintext fallback).
    """
    if not _HAS_CRYPTO:
        return None
    key = os.environ.get(KEY_ENV)
    if key:
        return key.encode() if isinstance(key, str) else key
    # Try key file
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, 'rb') as f:
            key = f.read().strip()
            os.environ[KEY_ENV] = key.decode(
            ) if isinstance(key, bytes) else key
            return key
    # Generate new key
    key = Fernet.generate_key()
    try:
        with open(KEY_FILE, 'wb') as f:
            f.write(key)
        try:
            os.chmod(KEY_FILE, 0o600)
        except Exception:
            pass
    except Exception:
        # If we cannot write, still return key (ephemeral for this session)
        pass
    os.environ[KEY_ENV] = key.decode()
    return key


def _get_cipher():
    if not _HAS_CRYPTO:
        return None
    key = _ensure_key()
    if not key:
        return None
    return Fernet(key)


def encrypt_text(plain: Optional[str]) -> Optional[bytes]:
    if plain is None:
        return None
    cipher = _get_cipher()
    if not cipher:
        return plain.encode('utf-8')  # fallback noop store
    return cipher.encrypt(plain.encode('utf-8'))


def decrypt_text(blob: Optional[bytes]) -> Optional[str]:
    if blob is None:
        return None
    cipher = _get_cipher()
    if not cipher:
        try:
            return blob.decode('utf-8')
        except Exception:
            return None
    try:
        return cipher.decrypt(blob).decode('utf-8')
    except Exception:
        return None


# ------------- DB Core -------------
def _get_conn():
    return sqlite3.connect(DB_PATH)


def init_db(migrate: bool = True):
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS servers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip TEXT NOT NULL UNIQUE,
                ssh_user TEXT NOT NULL,
                ssh_password_enc BLOB NULL,
                ssh_port INTEGER NOT NULL DEFAULT 22,
                os_type TEXT NOT NULL,
                parent_ip TEXT NULL,
                ssh_key_path TEXT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth_users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_enc BLOB NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value_enc BLOB NULL,
                is_secret INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.commit()
    finally:
        conn.close()
    if migrate:
        _maybe_migrate_from_config()
        _maybe_migrate_env_settings()


# ------------- Migration -------------
def _maybe_migrate_from_config():
    """Populate DB from config.py constants if empty.

    Safe to call multiple times; will not duplicate records.
    """
    try:
        from config import SERVERS, AUTH_USERS, AUTH_PASSWORDS, ADMIN_USERS  # type: ignore
    except Exception:
        return
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM servers')
        if cur.fetchone()[0] == 0:
            for s in SERVERS:
                # Attempt to resolve a real password from env if present
                pwd = None
                if s.get('ssh_password'):
                    pwd = s.get('ssh_password')
                else:
                    env_key = s.get('ssh_password_env')
                    if env_key:
                        pwd = os.environ.get(env_key)
                enc = encrypt_text(pwd) if pwd else None
                cur.execute('''
                    INSERT OR IGNORE INTO servers(name, ip, ssh_user, ssh_password_enc, ssh_port, os_type, parent_ip, ssh_key_path)
                    VALUES(?,?,?,?,?,?,?,?)
                ''', (
                    s.get('name'), s.get('ip'), s.get('ssh_user'), enc,
                    int(s.get('ssh_port', 22)), s.get('os_type', 'linux'),
                    s.get('parent'), s.get('ssh_key_path')
                ))
        cur.execute('SELECT COUNT(*) FROM auth_users')
        if cur.fetchone()[0] == 0:
            for u in AUTH_USERS:
                pwd = AUTH_PASSWORDS.get(u)
                enc = encrypt_text(pwd) if pwd else None
                is_admin = 1 if u in ADMIN_USERS else 0
                cur.execute('''
                    INSERT OR IGNORE INTO auth_users(username, password_enc, is_admin)
                    VALUES(?,?,?)
                ''', (u, enc, is_admin))
        conn.commit()
    finally:
        conn.close()


def _maybe_migrate_env_settings():
    """Store selected environment-provided settings if not present in DB.

    Focus on Telegram credentials for now.
    """
    keys = [
        'TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_CHAT_ID',
        'TELEGRAM_DEFAULT_LIMIT', 'TELEGRAM_REFRESH_INTERVAL'
    ]
    for k in keys:
        val = os.environ.get(k)
        if not val:
            continue
        if get_setting(k) is None:
            try:
                set_setting(k, val, secret=(
                    'HASH' in k or 'API_ID' in k or 'CHAT_ID' in k))
            except Exception:
                pass


# ------------- Public Accessors -------------
def load_servers() -> List[Dict[str, any]]:
    try:
        conn = _get_conn()
    except Exception as e:
        print(f"[secure_config_store] DB open failed, using cache: {e}")
        servers, _ = _cache_load()
        return servers
    servers: List[Dict[str, any]] = []
    try:
        cur = conn.cursor()
        for row in cur.execute('SELECT name, ip, ssh_user, ssh_password_enc, ssh_port, os_type, parent_ip, ssh_key_path FROM servers ORDER BY id'):
            (name, ip, user, pwd_enc, port, os_type, parent_ip, key_path) = row
            pwd = decrypt_text(pwd_enc) if pwd_enc else None
            servers.append({
                'name': name,
                'ip': ip,
                'ssh_user': user,
                'ssh_password': pwd,  # decrypted (runtime only)
                'ssh_password_env': None,  # migrated
                'ssh_port': port,
                'os_type': os_type,
                'parent': parent_ip,
                'ssh_key_path': key_path
            })
    except Exception as e:
        print(f"[secure_config_store] query servers failed, using cache: {e}")
        servers, _ = _cache_load()
        return servers
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # update cache (need user data to keep aligned)
    try:
        users = _list_users_with_pw()
        _cache_write(servers, users)
    except Exception:
        pass
    return servers


def get_user_password(username: str) -> Optional[str]:
    try:
        conn = _get_conn()
    except Exception:
        # fallback to cache
        _, users_map = _cache_load()
        entry = users_map.get(username)
        return entry.get('password') if entry else None
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT password_enc FROM auth_users WHERE username = ?', (username,))
        row = cur.fetchone()
        if not row:
            return None
        enc = row[0]
        return decrypt_text(enc) if enc else None
    except Exception as e:
        print(
            f"[secure_config_store] user password query failed, using cache: {e}")
        _, users_map = _cache_load()
        entry = users_map.get(username)
        return entry.get('password') if entry else None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_users() -> List[str]:
    try:
        conn = _get_conn()
    except Exception:
        _, users_map = _cache_load()
        return sorted(users_map.keys())
    try:
        cur = conn.cursor()
        rows = cur.execute(
            'SELECT username FROM auth_users ORDER BY username').fetchall()
        names = [r[0] for r in rows]
    except Exception as e:
        print(f"[secure_config_store] list_users failed, using cache: {e}")
        _, users_map = _cache_load()
        names = sorted(users_map.keys())
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return names


def is_admin(username: str) -> bool:
    try:
        conn = _get_conn()
    except Exception:
        _, users_map = _cache_load()
        entry = users_map.get(username)
        return bool(entry and entry.get('is_admin'))
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT is_admin FROM auth_users WHERE username = ?', (username,))
        row = cur.fetchone()
        return bool(row and row[0])
    except Exception as e:
        print(f"[secure_config_store] is_admin failed, using cache: {e}")
        _, users_map = _cache_load()
        entry = users_map.get(username)
        return bool(entry and entry.get('is_admin'))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def upsert_user(username: str, password: Optional[str], is_admin_flag: bool = False):
    try:
        conn = _get_conn()
    except Exception as e:
        print(
            f"[secure_config_store] upsert_user DB open failed (cache only): {e}")
        # mutate cache directly (load existing + overwrite)
        servers, users_map = _cache_load()
        users_map[username] = {'password': password, 'is_admin': is_admin_flag}
        users_list = [(u, v.get('password'), v.get('is_admin'))
                      for u, v in users_map.items()]
        _cache_write(servers, users_list)
        return
    try:
        cur = conn.cursor()
        enc = encrypt_text(password) if password else None
        cur.execute('''
            INSERT INTO auth_users(username, password_enc, is_admin)
            VALUES(?,?,?)
            ON CONFLICT(username) DO UPDATE SET
                password_enc=coalesce(excluded.password_enc, auth_users.password_enc),
                is_admin=excluded.is_admin
        ''', (username, enc, 1 if is_admin_flag else 0))
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # refresh cache
    try:
        servers = load_servers()
        users = _list_users_with_pw()
        _cache_write(servers, users)
    except Exception:
        pass


def upsert_server(server: Dict[str, any]):
    try:
        conn = _get_conn()
    except Exception as e:
        print(
            f"[secure_config_store] upsert_server DB open failed (cache only): {e}")
        servers, users_map = _cache_load()
        # replace or append
        updated = False
        for i, s in enumerate(servers):
            if s.get('ip') == server.get('ip'):
                servers[i] = {**s, **server}
                updated = True
                break
        if not updated:
            servers.append(server)
        users_list = [(u, v.get('password'), v.get('is_admin'))
                      for u, v in users_map.items()]
        _cache_write(servers, users_list)
        return
    try:
        cur = conn.cursor()
        pwd = server.get('ssh_password')
        enc = encrypt_text(pwd) if pwd else None
        cur.execute('''
            INSERT INTO servers(name, ip, ssh_user, ssh_password_enc, ssh_port, os_type, parent_ip, ssh_key_path)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(ip) DO UPDATE SET
                name=excluded.name,
                ssh_user=excluded.ssh_user,
                ssh_password_enc=coalesce(excluded.ssh_password_enc, servers.ssh_password_enc),
                ssh_port=excluded.ssh_port,
                os_type=excluded.os_type,
                parent_ip=excluded.parent_ip,
                ssh_key_path=excluded.ssh_key_path
        ''', (
            server.get('name'), server.get('ip'), server.get('ssh_user'), enc,
            int(server.get('ssh_port', 22)), server.get('os_type', 'linux'),
            server.get('parent'), server.get('ssh_key_path')
        ))
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # refresh cache
    try:
        servers = load_servers()
        users = _list_users_with_pw()
        _cache_write(servers, users)
    except Exception:
        pass


def _list_users_with_pw() -> List[Tuple[str, Optional[str], bool]]:
    """Internal helper to extract (username,password,is_admin) from DB (no cache fallback)."""
    out: List[Tuple[str, Optional[str], bool]] = []
    try:
        conn = _get_conn()
    except Exception:
        return out
    try:
        cur = conn.cursor()
        for row in cur.execute('SELECT username, password_enc, is_admin FROM auth_users'):
            uname, pw_enc, adm = row
            out.append((uname, decrypt_text(pw_enc)
                       if pw_enc else None, bool(adm)))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


# ------------- Settings -------------
def set_setting(key: str, value: Optional[str], secret: bool = True):
    if value is None:
        return
    try:
        conn = _get_conn()
    except Exception as e:
        print(f"[secure_config_store] set_setting DB open failed: {e}")
        return
    try:
        cur = conn.cursor()
        enc = encrypt_text(value) if secret else encrypt_text(value)
        cur.execute('''
            INSERT INTO settings(key, value_enc, is_secret) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value_enc=excluded.value_enc, is_secret=excluded.is_secret
        ''', (key, enc, 1 if secret else 0))
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_setting(key: str) -> Optional[str]:
    try:
        conn = _get_conn()
    except Exception:
        return None
    try:
        cur = conn.cursor()
        cur.execute('SELECT value_enc FROM settings WHERE key=?', (key,))
        row = cur.fetchone()
        if not row:
            return None
        return decrypt_text(row[0]) if row[0] else None
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


# Initialize database (non-migrating by default when imported elsewhere).  The
# main application will call init_db(migrate=True) explicitly.
if os.environ.get('COBALTAX_SECURE_STORE_AUTO_INIT', '1') == '1':
    try:
        init_db(migrate=True)
    except Exception as _e:  # pragma: no cover (best effort)
        print(f"[secure_config_store] init warning: {_e}")
