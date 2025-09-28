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
import argparse
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
    parser = argparse.ArgumentParser(
        description="Seal environment variables into encrypted SQLite store")
    parser.add_argument('--env-file', dest='env_file',
                        help='Explicit .env file to load (defaults: .env, _.env)', default=None)
    args = parser.parse_args()

    def load_env_file(path: str):
        if not os.path.exists(path):
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    # Don't override already exported values (caller precedence)
                    if k and v and k not in os.environ:
                        os.environ[k] = v
            return True
        except Exception as e:
            print(f"Warning: failed to parse env file {path}: {e}")
            return False

    # Load env file(s) BEFORE init_db so migration picks them up
    loaded_file = None
    if args.env_file:
        if load_env_file(args.env_file):
            loaded_file = args.env_file
        else:
            print(f"Specified env file not loaded: {args.env_file}")
    else:
        for candidate in ('.env', '_.env'):  # support your current naming
            if load_env_file(candidate):
                loaded_file = candidate
                break
    if loaded_file:
        print(f"Loaded environment variables from {loaded_file}")
    else:
        print("No env file loaded (relying on existing process environment)")

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
