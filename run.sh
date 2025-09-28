#!/bin/bash

# CobaltaX Server Monitor Setup Script
# Do NOT place secrets directly in this file. Use a .env file instead.

set -euo pipefail

# Load dotenv if present
if [ -f .env ]; then
	echo "Loading environment from .env"
	# Robust, POSIX-safe: export all variables defined in .env (no spaces around '=')
	# Supports comments (#) and blank lines.
	set -o allexport
	# shellcheck disable=SC1091
	. ./.env
	set +o allexport
fi

echo "Optionally run: python scripts/telegram_login.py (first time to create session)"

echo "🎯 Starting Server Monitor..."
python server_monitor.py