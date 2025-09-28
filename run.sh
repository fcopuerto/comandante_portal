#!/bin/bash

# CobaltaX Server Monitor Setup Script
# Do NOT place secrets directly in this file. Use a .env file instead.
#This iniitializes the sqlite with the .env parames
#python scripts/init_from_env.py --env-file _.env
#
set -euo pipefail

# Load dotenv if present (prefer .env else fallback to _.env legacy filename)
ENV_FILE=""
if [ -f .env ]; then
	ENV_FILE=".env"
elif [ -f _.env ]; then
	ENV_FILE="_.env"
fi
if [ -n "$ENV_FILE" ]; then
	echo "Loading environment from $ENV_FILE"
	set -o allexport
	# shellcheck disable=SC1091
	. "./$ENV_FILE"
	set +o allexport
fi

# Auto-seal Telegram settings into secure store if not already present
python - <<'PYEOF'
import os, sys
missing=False
try:
		from secure_config_store import get_setting, set_setting
except Exception:
		sys.exit(0)
keys=['TELEGRAM_API_ID','TELEGRAM_API_HASH','TELEGRAM_CHAT_ID','TELEGRAM_DEFAULT_LIMIT','TELEGRAM_REFRESH_INTERVAL']
for k in keys:
		if get_setting(k) is None:
				val=os.environ.get(k)
				if val:
						set_setting(k, val, secret= 'HASH' in k or 'API' in k or 'CHAT' in k)
						print(f"[seal] Stored {k} into secure settings store.")
				else:
						if k in ('TELEGRAM_API_ID','TELEGRAM_API_HASH','TELEGRAM_CHAT_ID'): missing=True
if missing:
		print("[seal] Telegram core credentials incomplete; you can enter them interactively in the UI.")
PYEOF

echo "Optionally run: python scripts/telegram_login.py (first time to create session)"

echo "🎯 Starting Server Monitor..."
python server_monitor.py