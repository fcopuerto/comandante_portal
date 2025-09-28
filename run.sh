#!/bin/bash

# CobaltaX Server Monitor Setup Script
# Do NOT place secrets directly in this file. Use a .env file instead.

set -euo pipefail

# Load dotenv if present
if [ -f .env ]; then
	echo "Loading environment from .env"
	# shellcheck disable=SC2046
	export $(grep -v '^#' .env | grep -v '^$' | cut -d= -f1)
fi

echo "Optionally run: python scripts/telegram_login.py (first time to create session)"

echo "🎯 Starting Server Monitor..."
python server_monitor.py