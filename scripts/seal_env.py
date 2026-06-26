#!/usr/bin/env python3
"""Move all non-MSSQL entries from .env into SQL Server cobaltax_settings,
then rewrite .env so it only contains the DB connection details.

Usage:
    python scripts/seal_env.py [path/to/.env]

Safe to run multiple times — existing DB settings are never overwritten.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Load MSSQL creds from .env first so we can connect
ENV_PATH = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(".env")
if not ENV_PATH.exists():
    print(f"No .env file found at {ENV_PATH}")
    sys.exit(1)

raw_lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

# Parse all entries
entries: list[tuple[str, str]] = []   # (key, value)
for line in raw_lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    k, v = stripped.split("=", 1)
    k, v = k.strip(), v.strip().strip('"').strip("'")
    os.environ.setdefault(k, v)   # make MSSQL creds available for db.py
    entries.append((k, v))

# Keys that MUST stay in .env (bootstrap DB connection)
KEEP_IN_ENV = {"MSSQL_SERVER", "MSSQL_DATABASE", "MSSQL_USER", "MSSQL_PASSWORD",
               "MSSQL_PORT", "MSSQL_TRUSTED_CONNECTION", "MSSQL_ENCRYPT",
               "CONFIG_MASTER_KEY"}

_SECRET_PATTERNS = ("PASS", "HASH", "KEY", "SECRET", "TOKEN", "PASSWORD", "API_ID", "CHAT_ID")

from secure_config_store import get_setting, set_setting  # noqa: E402  (needs env loaded first)

to_env: list[tuple[str, str]] = []
to_db:  list[tuple[str, str, bool]] = []

for k, v in entries:
    if k in KEEP_IN_ENV:
        to_env.append((k, v))
    else:
        secret = any(p in k for p in _SECRET_PATTERNS)
        to_db.append((k, v, secret))

print(f"\nFound {len(entries)} entries in {ENV_PATH}")
print(f"  Keeping in .env: {[k for k,v in to_env]}")
print(f"  Moving to SQL Server: {[k for k,v,s in to_db]}")

# Save to DB (skip if already present)
saved = skipped = 0
for k, v, secret in to_db:
    if get_setting(k) is not None:
        print(f"  [skip] {k} — already in DB")
        skipped += 1
    else:
        set_setting(k, v, secret=secret)
        print(f"  [saved] {k}")
        saved += 1

print(f"\n{saved} saved, {skipped} already existed in DB.")

# Rewrite .env
new_content = (
    "# CobaltaX — SQL Server connection (all other config is in the database)\n"
    + "\n".join(f"{k}={v}" for k, v in to_env)
    + "\n"
)
ENV_PATH.write_text(new_content, encoding="utf-8")
ENV_PATH.chmod(0o600)
print(f"\n.env rewritten — now contains only: {[k for k,v in to_env]}")
print("Done.")
