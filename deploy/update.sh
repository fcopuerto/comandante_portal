#!/usr/bin/env bash
# CobaltaX — pull latest code and restart the service.
# Run as root: sudo bash deploy/update.sh
set -euo pipefail

APP_DIR=/opt/cobaltax
APP_USER=cobaltax
SERVICE=cobaltax

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash deploy/update.sh"; exit 1; }

echo ":: Pulling latest code..."
git -C "$APP_DIR" pull --ff-only

echo ":: Syncing dependencies..."
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && uv sync --python '.venv/bin/python'"

echo ":: Restarting service..."
systemctl restart "$SERVICE"
systemctl --no-pager status "$SERVICE"

echo "Done. Logs: journalctl -u $SERVICE -f"
