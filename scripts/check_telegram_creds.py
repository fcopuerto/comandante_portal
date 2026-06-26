#!/usr/bin/env python3
"""Check and print TELEGRAM API credentials stored in the secure store.

Usage:
  python3 scripts/check_telegram_creds.py

This prints whether TELEGRAM_API_ID/HASH are present and shows a masked hash.
"""
from __future__ import annotations

import sys
import os

# Ensure project root (parent of scripts/) is on sys.path so top-level modules import correctly
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from secure_config_store import get_setting  # type: ignore
except Exception as e:
    print(f"secure_config_store import failed: {e}\nHint: run from project root or ensure PYTHONPATH includes the repo root: {_ROOT}")
    sys.exit(1)


def mask(s: str) -> str:
    if not s:
        return '(none)'
    if len(s) <= 8:
        return s[:2] + '...' + s[-2:]
    return s[:4] + '...' + s[-4:]


def main() -> None:
    aid = get_setting('TELEGRAM_API_ID')
    ah = get_setting('TELEGRAM_API_HASH')
    print('TELEGRAM_API_ID :', aid if aid else '(none)')
    print('TELEGRAM_API_HASH:', mask(ah) if ah else '(none)')


if __name__ == '__main__':
    main()
