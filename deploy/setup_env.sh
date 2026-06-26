#!/usr/bin/env bash
# CobaltaX .env wizard — generates the minimal env file needed to connect to SQL Server.
# All other config (users, passwords, servers, Telegram) lives in the database.
# Usage: bash deploy/setup_env.sh [output_path]
set -euo pipefail

OUT="${1:-.env}"

ask() {
    local label="$1" var="$2" default="${3:-}"
    if [[ -n "$default" ]]; then
        read -rp "$label [$default]: " val
        val="${val:-$default}"
    else
        read -rp "$label: " val
    fi
    printf '%s=%s\n' "$var" "$val" >> "$OUT"
}

ask_secret() {
    local label="$1" var="$2"
    read -rsp "$label (hidden): " val; echo
    printf '%s=%s\n' "$var" "$val" >> "$OUT"
}

echo "=== CobaltaX .env setup ==="
echo "Output: $OUT"
echo "All app config lives in SQL Server — this file only needs the DB connection."
echo

> "$OUT"

echo "--- SQL Server connection ---"
ask        "Server hostname or IP"  "MSSQL_SERVER"   "sqlserver.cobaltax.local"
ask        "Database name"          "MSSQL_DATABASE" "cobaltax"
ask        "SQL login username"     "MSSQL_USER"     "cobaltax_app"
ask_secret "SQL login password"     "MSSQL_PASSWORD"
ask        "Port"                   "MSSQL_PORT"     "1433"

echo
echo "--- Encryption key for passwords stored in DB ---"
echo "(Leave blank to auto-generate on first run — the key will be saved to ~/.cobaltax/.config_master.key)"
read -rsp "CONFIG_MASTER_KEY (blank = auto): " mk; echo
if [[ -n "$mk" ]]; then
    printf 'CONFIG_MASTER_KEY=%s\n' "$mk" >> "$OUT"
fi

chmod 600 "$OUT"
echo
echo ".env written to: $OUT  (permissions: 600)"
