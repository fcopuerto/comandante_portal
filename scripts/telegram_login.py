#!/usr/bin/env python3
"""Interactive helper to create a user session for full Telegram history.

Usage:
  1. Run: python scripts/telegram_login.py
  2. Follow the prompts (phone number, login code, 2FA password if enabled).
  3. A session file ~/.cobaltax/cobaltax_user_session(.session) will be created.

The script will look for TELEGRAM_API_ID/TELEGRAM_API_HASH in this order:
  1) CLI args --api-id / --api-hash
  2) secure_config_store.settings (if available)
  3) dotenv candidates (./.env, ./_.env, ./.env.cobaltax)
  4) environment variables

This keeps behaviour consistent with the GUI which reads the secure store and
uses ~/.cobaltax for the session file.
"""
from __future__ import annotations

import os
import sys
import argparse

try:
    from telethon.sync import TelegramClient  # type: ignore
except Exception:
    print("telethon not installed. Install with: pip install telethon")
    sys.exit(1)


def _load_dotenv_candidates() -> None:
    """Load simple KEY=VALUE lines from common dotenv candidates into os.environ
    without overwriting existing keys."""
    candidates = ['.env', '_.env', '.env.cobaltax']
    for name in candidates:
        if os.path.exists(name):
            try:
                with open(name, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#') or '=' not in line:
                            continue
                        k, v = line.split('=', 1)
                        k = k.strip(); v = v.strip()
                        if k and v and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


def _get_from_secure_store(key: str) -> str:
    try:
        from secure_config_store import decrypt_text, _get_conn  # type: ignore
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT value_enc FROM settings WHERE key=?', (key,))
            row = cur.fetchone()
            if row and row[0]:
                try:
                    return decrypt_text(row[0]) or ''
                except Exception:
                    try:
                        return row[0].decode('utf-8') if isinstance(row[0], (bytes, bytearray)) else str(row[0])
                    except Exception:
                        return ''
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return ''
    return ''


def main() -> None:
    ap = argparse.ArgumentParser(description='Create Telethon user session for CobaltaX')
    ap.add_argument('--api-id', help='Telegram API ID')
    ap.add_argument('--api-hash', help='Telegram API HASH')
    args = ap.parse_args()

    # Load dotenv candidates so users can keep a portable .env next to the script
    _load_dotenv_candidates()

    # Prefer CLI args, then secure store, then env
    api_id = args.api_id or _get_from_secure_store('TELEGRAM_API_ID') or os.environ.get('TELEGRAM_API_ID')
    api_hash = args.api_hash or _get_from_secure_store('TELEGRAM_API_HASH') or os.environ.get('TELEGRAM_API_HASH')

    if not api_id or not api_hash:
        print('Please set TELEGRAM_API_ID and TELEGRAM_API_HASH via --api-id/--api-hash, .env, secure store, or environment.')
        sys.exit(1)

    try:
        api_id_int = int(api_id)
    except Exception:
        print(f'Invalid TELEGRAM_API_ID: {api_id}')
        sys.exit(1)

    # Use the same per-user folder as secure_config_store and telethon_runner
    base = os.path.join(os.path.expanduser('~'), '.cobaltax')
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    SESSION_PATH = os.path.join(base, 'cobaltax_user_session')
    print(f'Using session path: {SESSION_PATH}.session')

    with TelegramClient(SESSION_PATH, api_id_int, api_hash) as client:
        if not client.is_user_authorized():
            phone = input('Enter your phone number (with country code, e.g. +1555123456): ').strip()
            client.send_code_request(phone)
            code = input('Enter the login code you received: ').strip()
            try:
                client.sign_in(phone=phone, code=code)
            except Exception as e:
                # 2FA password maybe required
                if 'password' in str(e).lower():
                    pw = input('Two-step password (leave blank to retry): ')
                    if pw:
                        client.sign_in(password=pw)
                    else:
                        print(f'Login failed: {e}')
                        sys.exit(1)
                else:
                    print(f'Login failed: {e}')
                    sys.exit(1)
        me = client.get_me()
        print(f"Logged in as: {getattr(me, 'username', None) or me.first_name} (id={me.id})")
        print('Session created. You can now use full history in the GUI.')


if __name__ == '__main__':
    main()
