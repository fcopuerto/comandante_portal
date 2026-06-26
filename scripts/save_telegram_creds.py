#!/usr/bin/env python3
"""Save TELEGRAM API credentials into the encrypted secure store.

Usage:
  python3 scripts/save_telegram_creds.py --id 123456 --hash abcd1234
  or
  python3 scripts/save_telegram_creds.py  (interactive prompt)

This script uses the repository's `secure_config_store.set_setting` API and
persists the values so the GUI and background Telethon runner can read them.
"""
from __future__ import annotations

import argparse
import getpass
import sys
import os

# Ensure project root (parent of scripts/) is on sys.path so top-level modules import correctly
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from secure_config_store import set_setting, get_setting  # type: ignore
except Exception as e:
    print(f"secure_config_store import failed: {e}\nHint: run from project root or ensure PYTHONPATH includes the repo root: {_ROOT}")
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description='Save TELEGRAM API credentials to secure store')
    ap.add_argument('--id', dest='api_id', help='Telegram API ID')
    ap.add_argument('--hash', dest='api_hash', help='Telegram API HASH')
    args = ap.parse_args()

    api_id = args.api_id
    api_hash = args.api_hash

    if not api_id:
        api_id = input('Enter TELEGRAM_API_ID: ').strip()
    if not api_hash:
        # use getpass to avoid showing hash on screen
        api_hash = getpass.getpass('Enter TELEGRAM_API_HASH: ').strip()

    if not api_id or not api_hash:
        print('Both TELEGRAM_API_ID and TELEGRAM_API_HASH are required.')
        sys.exit(1)

    try:
        set_setting('TELEGRAM_API_ID', str(api_id))
        set_setting('TELEGRAM_API_HASH', str(api_hash))
        print('Saved TELEGRAM_API_ID and TELEGRAM_API_HASH to secure store.')
    except Exception as e:
        print(f'Failed to save credentials: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
