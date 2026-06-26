#!/usr/bin/env python3
"""Seed portal-specific config (printers, apps, backups, network description)
into cobaltax_settings so the code no longer needs hardcoded values.

Run once after init_db.py:
    python scripts/seed_portal_config.py

Edit the DATA dict below before running on a new installation.
Safe to re-run — existing DB values are never overwritten.
"""
from __future__ import annotations
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

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

# ── Edit this section for your installation ───────────────────────────────────

DATA = {
    # key in cobaltax_settings → value (string or JSON-serialisable object)
    "printers_list": [
        # {"name": "...", "location": "...", "ip": "...", "subnet": "...", "link": "data/printers/..."},
    ],
    "monitored_apps": [
        # {"id": "myapp", "name": "My App", "url": "http://server.local/", "server": "server.local"},
    ],
    "backup_jobs": [
        # {"id": "backup_nas", "name": "NAS backup", "server": "nas-server",
        #  "last_backup": "", "retention": "30 days", "type": "daily"},
    ],
    # Free-text network description injected into the AI assistant prompt.
    # Leave empty and fill via the web UI settings page.
    "NETWORK_DESCRIPTION": "",
}

# ─────────────────────────────────────────────────────────────────────────────

from secure_config_store import get_setting, set_setting  # noqa: E402

saved = skipped = 0
for key, value in DATA.items():
    serialised = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if not serialised or serialised in ("[]", "{}"):
        print(f"  [skip] {key} — empty, set via web UI")
        continue
    if get_setting(key) is not None:
        print(f"  [skip] {key} — already in DB")
        skipped += 1
    else:
        set_setting(key, serialised, secret=False)
        print(f"  [saved] {key}")
        saved += 1

print(f"\n{saved} saved, {skipped} already in DB.")
print("Edit DATA in this script before running on a new installation.")
