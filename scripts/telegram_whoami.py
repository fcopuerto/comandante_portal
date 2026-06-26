#!/usr/bin/env python3
"""Print the identity of the current Telethon session (user vs bot).

Usage:
  python3 scripts/telegram_whoami.py

Requirements:
  - TELEGRAM_API_ID/HASH saved to secure store (or in env)
  - Session at ~/.cobaltax/cobaltax_user_session created via scripts/telegram_login.py
"""
from __future__ import annotations

import os
import sys

# Ensure repo root on path
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from telethon.sync import TelegramClient
except Exception:
    print('telethon not installed. Install with: pip install telethon')
    sys.exit(1)

# Best-effort read from secure store
try:
    from secure_config_store import get_setting  # type: ignore
except Exception:
    def get_setting(k: str):
        return os.environ.get(k)

def main() -> None:
    session = os.path.expanduser('~/.cobaltax/cobaltax_user_session')
    api_id = get_setting('TELEGRAM_API_ID')
    api_hash = get_setting('TELEGRAM_API_HASH')
    if not api_id or not api_hash:
        print('Missing TELEGRAM_API_ID/HASH. Save them with scripts/save_telegram_creds.py')
        sys.exit(1)
    try:
        api_id_int = int(api_id)
    except Exception:
        print(f'Invalid TELEGRAM_API_ID: {api_id}')
        sys.exit(1)

    with TelegramClient(session, api_id_int, api_hash) as client:
        me = client.get_me()
        print('username:', getattr(me, 'username', None) or getattr(me, 'first_name', None))
        print('id      :', getattr(me, 'id', None))
        print('is_bot  :', getattr(me, 'bot', False))

if __name__ == '__main__':
    main()
