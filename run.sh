#!/bin/bash

# CobaltaX Server Monitor — web edition
# Do NOT place secrets directly in this file. Use a .env file instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load dotenv safely (supports inline comments, quoted values)
for ENV_FILE in .env .env.cobaltax _.env; do
  if [ -f "$SCRIPT_DIR/$ENV_FILE" ]; then
    echo "Loading environment from $ENV_FILE"
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line%%#*}"
      line="${line#"${line%%[![:space:]]*}"}"
      line="${line%"${line##*[![:space:]]}"}"
      [ -z "$line" ] && continue
      [[ "$line" != *=* ]] && continue
      key="${line%%=*}"
      val="${line#*=}"
      val="${val#\"}" ; val="${val%\"}"
      val="${val#\'}" ; val="${val%\'}"
      export "$key=$val"
    done < "$SCRIPT_DIR/$ENV_FILE"
  fi
done

# Resolve runner: prefer uv, then .venv, then system python3
if command -v uv &>/dev/null; then
  echo "Using uv — syncing environment..."
  uv sync --quiet
  echo "Starting CobaltaX Server Monitor web interface..."
  echo "Open http://localhost:8080 in your browser."
  exec uv run python "$SCRIPT_DIR/main.py" "$@"
elif [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  echo "Starting CobaltaX Server Monitor web interface..."
  echo "Open http://localhost:8080 in your browser."
  exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
elif command -v python3 &>/dev/null; then
  echo "Starting CobaltaX Server Monitor web interface..."
  echo "Open http://localhost:8080 in your browser."
  exec python3 "$SCRIPT_DIR/main.py" "$@"
else
  echo "ERROR: no Python found. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
