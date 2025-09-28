#!/usr/bin/env python3
"""One-time initialization helper.

Purpose:
  - Load environment / .env (if present and sourced beforehand)
  - Initialize encrypted SQLite config store (servers, users, settings)
  - Persist Telegram settings & credentials in DB
  - Optionally produce a sanitized .env output (future enhancement)

Usage:
  1. Ensure your .env is loaded (source it) or export variables.
  2. Run: python scripts/init_from_env.py
  3. Verify summary. If OK, you can remove/rename the .env for production.

The regular application will then run without needing those environment
variables (unless you add new servers/users; use upsert helpers or rerun).
"""
from __future__ import annotations
import os
import sys
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from secure_config_store import (  # type: ignore
        init_db, load_servers, list_users, get_setting,
        set_setting, upsert_server, upsert_user
    )
except ModuleNotFoundError as e:  # pragma: no cover
    print("Error: could not import secure_config_store. Make sure you run this script from the project root, e.g.:\n  python scripts/init_from_env.py")
    print(f"Details: {e}")
    sys.exit(1)


def main():
    init_db(migrate=True)

    # After migration, ensure Telegram settings captured if present
    for k in ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_CHAT_ID', 'TELEGRAM_DEFAULT_LIMIT', 'TELEGRAM_REFRESH_INTERVAL']:
        val = os.environ.get(k)
        if val and get_setting(k) is None:
            set_setting(k, val, secret=(
                'HASH' in k or 'API' in k or 'CHAT_ID' in k))

    servers = load_servers()
    users = list_users()

    print("Initialization complete:")
    print(f"  Servers stored: {len(servers)}")
    print(f"  Users stored:   {len(users)}")
    missing_settings = [k for k in [
        'TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_CHAT_ID'] if get_setting(k) is None]
    if missing_settings:
        print(
            f"  Warning: Missing Telegram settings in DB: {missing_settings}")
    else:
        print("  Telegram settings sealed in DB.")

    print("\nYou may now remove or restrict the original .env file for production.")
    print("(Keep a secure backup of .config_master.key and the SQLite DB)")


if __name__ == '__main__':
    sys.exit(main())
