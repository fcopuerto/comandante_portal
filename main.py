"""Entry point for CobaltaX Server Monitor (web edition).

Startup order:
  1. Load .env (MSSQL connection details only)
  2. Inject all other settings from SQL Server into os.environ
  3. Import and run web_app (config.py / ldap_auth.py read os.environ at import time)
"""
from __future__ import annotations
import os
import sys

# Optional: wipe all cobaltax tables in SQL Server (development / support use)
if '--reset-store' in sys.argv:
    print("WARNING: this will DROP all cobaltax_* tables from SQL Server.")
    confirm = input("Type YES to continue: ")
    if confirm.strip() == 'YES':
        from db import get_conn
        tables = [
            'cobaltax_chat_messages', 'cobaltax_conversations',
            'cobaltax_energy_readings',
            'cobaltax_settings', 'cobaltax_auth_users', 'cobaltax_servers',
        ]
        with get_conn() as conn:
            cur = conn.cursor()
            for t in tables:
                cur.execute(f"IF OBJECT_ID('{t}', 'U') IS NOT NULL DROP TABLE {t}")
        print("Tables dropped. Run scripts/init_db.py to recreate.")
    else:
        print("Aborted.")
    sys.exit(0)

# ── 1. Load .env (only MSSQL connection details live here now) ────────────────
for _candidate in ('.env', '.env.cobaltax', '_.env'):
    if os.path.exists(_candidate):
        try:
            with open(_candidate, 'r', encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if not _line or _line.startswith('#') or '=' not in _line:
                        continue
                    _k, _v = _line.split('=', 1)
                    _k, _v = _k.strip(), _v.strip()
                    if _k not in os.environ:
                        os.environ[_k] = _v
        except Exception:
            pass
        break

# ── 2. Inject all remaining settings from SQL Server ─────────────────────────
# Disable auto-init so importing secure_config_store doesn't trigger a
# redundant init_db() call before we've finished setting up the environment.
os.environ['COBALTAX_SECURE_STORE_AUTO_INIT'] = '0'
try:
    from secure_config_store import inject_settings_to_env
    n = inject_settings_to_env()
    if n:
        print(f"[main] Loaded {n} settings from SQL Server.")
except Exception as _e:
    print(f"[main] Warning: could not inject settings from DB: {_e}")
finally:
    os.environ.pop('COBALTAX_SECURE_STORE_AUTO_INIT', None)

# ── 3. Parse --host / --port flags ────────────────────────────────────────────
host = '0.0.0.0'
port = 8080
for arg in sys.argv[1:]:
    if arg.startswith('--host='):
        host = arg.split('=', 1)[1]
    elif arg.startswith('--port='):
        port = int(arg.split('=', 1)[1])

# ── 4. Start the app (web_app imports config.py + ldap_auth.py here) ─────────
from web_app import run
run(host=host, port=port)
