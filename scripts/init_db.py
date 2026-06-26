#!/usr/bin/env python3
"""CobaltaX — initialise SQL Server schema and migrate local data.

Run once on first deployment (or after wiping the database):

    python scripts/init_db.py [--migrate-local]

What this script does
---------------------
1. Creates all tables in MSSQL (IF NOT EXISTS):
     cobaltax_servers, cobaltax_auth_users, cobaltax_settings
     cobaltax_conversations, cobaltax_chat_messages
     tickets, ticket_comments, ticket_attachments  (support module)

2. If --migrate-local is given (or local SQLite files are found):
     - Reads ~/.cobaltax/config_store.sqlite and copies servers, users, settings
     - Reads ~/.cobaltax/chat_history.sqlite and copies conversations + messages

3. Seeds from config.py if the MSSQL tables are still empty after step 2.

Connection is configured via .env / environment:
  MSSQL_SERVER, MSSQL_DATABASE, MSSQL_USER, MSSQL_PASSWORD
  (or MSSQL_TRUSTED_CONNECTION=true for Windows Auth)
"""
from __future__ import annotations

import argparse
import os
import sys
import pathlib

# Allow running from repo root
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Load .env if present
for _env in (".env", ".env.cobaltax", "_.env"):
    _p = pathlib.Path(__file__).resolve().parents[1] / _env
    if _p.exists():
        for _line in _p.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            k, v = _line.split("=", 1)
            if k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip().strip('"').strip("'")
        break


def _header(msg: str) -> None:
    print(f"\n\033[36m── {msg}\033[0m")


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _warn(msg: str) -> None:
    print(f"  \033[33m!\033[0m {msg}")


def create_schema() -> None:
    _header("Creating schema")
    # Config + auth tables
    import secure_config_store
    secure_config_store.init_db(migrate=False)
    _ok("cobaltax_servers, cobaltax_auth_users, cobaltax_settings")

    # Chat tables
    import chat_db
    chat_db.init_db()
    _ok("cobaltax_conversations, cobaltax_chat_messages")

    # Energy history table (inline — web_app owns this)
    from db import get_conn
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            IF OBJECT_ID('cobaltax_energy_readings', 'U') IS NULL
            BEGIN
                CREATE TABLE cobaltax_energy_readings (
                    ip    NVARCHAR(50) NOT NULL,
                    ts    FLOAT        NOT NULL,
                    watts FLOAT        NOT NULL
                );
                CREATE INDEX idx_er_ip_ts ON cobaltax_energy_readings(ip, ts);
            END
        """)
    _ok("cobaltax_energy_readings")

    # Support tables
    import support_db
    support_db.init_db()
    _ok("tickets, ticket_comments, ticket_attachments")


def migrate_sqlite_config() -> None:
    """Copy data from ~/.cobaltax/config_store.sqlite → MSSQL."""
    sqlite_path = pathlib.Path.home() / ".cobaltax" / "config_store.sqlite"
    if not sqlite_path.exists():
        _warn(f"No local config SQLite found at {sqlite_path}, skipping.")
        return

    _header(f"Migrating config from {sqlite_path}")
    import sqlite3
    import secure_config_store

    src = sqlite3.connect(sqlite_path)
    try:
        # ── Servers ───────────────────────────────────────────────────────────
        try:
            rows = src.execute(
                "SELECT name, ip, ssh_user, ssh_password_enc, ssh_port, os_type, "
                "parent_ip, ssh_key_path, watts_idle, watts_max, subnet, web_url "
                "FROM servers"
            ).fetchall()
        except Exception as e:
            _warn(f"Could not read servers table: {e}")
            rows = []

        for r in rows:
            (name, ip, ssh_user, pwd_enc_blob, ssh_port, os_type,
             parent_ip, ssh_key_path, watts_idle, watts_max, subnet, web_url) = r
            # Decrypt from old Fernet store
            pwd = secure_config_store._decrypt(pwd_enc_blob) if pwd_enc_blob else None
            secure_config_store.upsert_server({
                "name": name, "ip": ip, "ssh_user": ssh_user,
                "ssh_password": pwd, "ssh_port": ssh_port or 22,
                "os_type": os_type or "linux", "parent": parent_ip,
                "ssh_key_path": ssh_key_path, "watts_idle": watts_idle,
                "watts_max": watts_max, "subnet": subnet, "web_url": web_url,
            })
        _ok(f"{len(rows)} servers migrated")

        # ── Auth users ────────────────────────────────────────────────────────
        try:
            users = src.execute(
                "SELECT username, password_enc, is_admin FROM auth_users"
            ).fetchall()
        except Exception as e:
            _warn(f"Could not read auth_users table: {e}")
            users = []

        for uname, pw_enc, is_admin in users:
            pwd = secure_config_store._decrypt(pw_enc) if pw_enc else None
            secure_config_store.upsert_user(uname, pwd, bool(is_admin))
        _ok(f"{len(users)} users migrated")

        # ── Settings ──────────────────────────────────────────────────────────
        try:
            settings = src.execute(
                "SELECT [key], value_enc, is_secret FROM settings"
            ).fetchall()
        except Exception as e:
            _warn(f"Could not read settings table: {e}")
            settings = []

        for key, val_enc, is_secret in settings:
            val = secure_config_store._decrypt(val_enc) if val_enc else None
            if val and secure_config_store.get_setting(key) is None:
                secure_config_store.set_setting(key, val, secret=bool(is_secret))
        _ok(f"{len(settings)} settings migrated")

    finally:
        src.close()


def migrate_sqlite_chat() -> None:
    """Copy data from ~/.cobaltax/chat_history.sqlite → MSSQL."""
    sqlite_path = pathlib.Path.home() / ".cobaltax" / "chat_history.sqlite"
    if not sqlite_path.exists():
        _warn(f"No local chat SQLite found at {sqlite_path}, skipping.")
        return

    _header(f"Migrating chat history from {sqlite_path}")
    import sqlite3
    import chat_db

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    try:
        convs = src.execute(
            "SELECT id, user, title, created_at, updated_at FROM conversations ORDER BY id"
        ).fetchall()
        migrated_convs = migrated_msgs = 0
        for conv in convs:
            old_id = conv["id"]
            new_id = chat_db.create_conversation(conv["user"], conv["title"])
            msgs = src.execute(
                "SELECT role, content, created_at FROM chat_messages"
                " WHERE conversation_id=? ORDER BY id",
                (old_id,),
            ).fetchall()
            for m in msgs:
                chat_db.save_message(
                    conv["user"], m["role"], m["content"],
                    conversation_id=new_id,
                )
                migrated_msgs += 1
            migrated_convs += 1
        _ok(f"{migrated_convs} conversations, {migrated_msgs} messages migrated")
    finally:
        src.close()


def migrate_sqlite_energy() -> None:
    """Copy data from ~/.cobaltax/energy_history.sqlite → MSSQL."""
    sqlite_path = pathlib.Path.home() / ".cobaltax" / "energy_history.sqlite"
    if not sqlite_path.exists():
        _warn(f"No local energy SQLite found at {sqlite_path}, skipping.")
        return

    _header(f"Migrating energy history from {sqlite_path}")
    import sqlite3
    from db import get_conn

    src = sqlite3.connect(sqlite_path)
    try:
        rows = src.execute("SELECT ip, ts, watts FROM energy_readings ORDER BY ts").fetchall()
        if not rows:
            _ok("No energy readings to migrate.")
            return
        with get_conn() as conn:
            cur = conn.cursor()
            cur.executemany(
                "INSERT INTO cobaltax_energy_readings(ip, ts, watts) VALUES(?,?,?)", rows
            )
        _ok(f"{len(rows)} energy readings migrated")
    finally:
        src.close()


def seed_from_config() -> None:
    _header("Seeding from config.py (if tables are empty)")
    import secure_config_store
    secure_config_store.init_db(migrate=True)
    _ok("Done (config.py defaults applied if tables were empty)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialise CobaltaX SQL Server schema")
    parser.add_argument(
        "--migrate-local", action="store_true",
        help="Also migrate data from local SQLite files (auto-detected if files exist)",
    )
    parser.add_argument(
        "--no-seed", action="store_true",
        help="Skip seeding from config.py after migration",
    )
    args = parser.parse_args()

    print("CobaltaX — database initialisation")
    print(f"Target: {os.environ.get('MSSQL_SERVER','?')}/{os.environ.get('MSSQL_DATABASE','?')}")

    create_schema()

    # Auto-detect local SQLite even without --migrate-local flag
    local_config = pathlib.Path.home() / ".cobaltax" / "config_store.sqlite"
    local_chat   = pathlib.Path.home() / ".cobaltax" / "chat_history.sqlite"
    if args.migrate_local or local_config.exists():
        migrate_sqlite_config()
    if args.migrate_local or local_chat.exists():
        migrate_sqlite_chat()

    local_energy = pathlib.Path.home() / ".cobaltax" / "energy_history.sqlite"
    if args.migrate_local or local_energy.exists():
        migrate_sqlite_energy()

    if not args.no_seed:
        seed_from_config()

    print("\n\033[32mDatabase ready.\033[0m")


if __name__ == "__main__":
    main()
