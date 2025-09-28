#!/bin/bash

# CobaltaX Server Monitor Setup Script
# This script sets up and runs the server monitoring application
export TELEGRAM_API_ID=REDACTED
export TELEGRAM_API_HASH=REDACTED
export TELEGRAM_CHAT_ID=REDACTED
export TELEGRAM_DEFAULT_LIMIT=100
export TELEGRAM_REFRESH_INTERVAL=90
export COBALTAX_USER=admin
export COBALTAX_PASS='REDACTED'
export COBALTAX_ADMINS=Fran
python scripts/telegram_login.py   # (once, user phone login)
python server_monitor.py

# Run the application
echo "🎯 Starting Server Monitor..."
python server_monitor.py