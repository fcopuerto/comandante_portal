#!/usr/bin/env bash
# CobaltaX Server Monitor — Ubuntu installer
# Run once as root on a fresh Ubuntu 22.04+ machine:
#   sudo bash deploy/install.sh
set -euo pipefail

APP_DIR=/opt/cobaltax
APP_USER=cobaltax
SERVICE=cobaltax
PYTHON_MIN="3.11"
DOMAIN="${COBALTAX_DOMAIN:-portal.cobaltax.com}"

# ── helpers ────────────────────────────────────────────────────────────────────
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
info()  { printf '\033[36m:: %s\033[0m\n' "$*"; }
die()   { red "ERROR: $*"; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash deploy/install.sh"

# ── 1. System packages ─────────────────────────────────────────────────────────
info "Installing system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    build-essential libssl-dev libffi-dev \
    curl git iputils-ping openssh-client \
    libsasl2-dev libldap2-dev \
    unixodbc-dev

# Verify Python version
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" \
    || die "Python $PYTHON_MIN+ required, found $PY_VER. On Ubuntu 20.04 run: apt-get install python3.11"

# ── 2. Install uv (fast package manager) ──────────────────────────────────────
if ! command -v uv &>/dev/null; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Make available system-wide
    install -m 755 "$HOME/.cargo/bin/uv" /usr/local/bin/uv 2>/dev/null \
        || install -m 755 "$HOME/.local/bin/uv" /usr/local/bin/uv
fi
info "uv $(uv --version)"

# ── 3. Create system user ──────────────────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
    info "Creating system user '$APP_USER'..."
    useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin --create-home "$APP_USER"
fi

# ── 4. Copy application files ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
info "Installing app from $SCRIPT_DIR → $APP_DIR..."

# Copy everything except dev/build artifacts
rsync -a --delete \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='dist' \
    --exclude='build' \
    --exclude='*.egg-info' \
    --exclude='audit.log' \
    --exclude='cobaltax_user_session*' \
    --exclude='config_store.sqlite' \
    --exclude='config_cache.json' \
    --exclude='.env' \
    --exclude='.env.cobaltax' \
    --exclude='_.env' \
    "$SCRIPT_DIR/" "$APP_DIR/"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ── 5. Create virtual environment and install dependencies ─────────────────────
info "Creating virtual environment and installing dependencies..."
sudo -u "$APP_USER" bash -c "
    cd '$APP_DIR'
    uv venv .venv --python python3
    uv sync --python '$APP_DIR/.venv/bin/python'
"

# ── 6. Data directory ──────────────────────────────────────────────────────────
DATA_DIR="$APP_DIR/.cobaltax"
info "Preparing data directory $DATA_DIR..."
install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$DATA_DIR"

# ── 7. Environment file ────────────────────────────────────────────────────────
ENV_FILE="$APP_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    info "No .env found — running setup wizard..."
    bash "$(dirname "$0")/setup_env.sh" "$ENV_FILE"
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
else
    info ".env already exists — skipping setup wizard."
fi

# ── 8. Microsoft ODBC driver for SQL Server ───────────────────────────────────
if ! dpkg -l msodbcsql18 &>/dev/null && ! dpkg -l msodbcsql17 &>/dev/null; then
    info "Installing Microsoft ODBC Driver 18 for SQL Server..."
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
    # Detect Ubuntu codename (jammy=22.04, focal=20.04, noble=24.04)
    UBUNTU_CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
    curl -fsSL "https://packages.microsoft.com/config/ubuntu/$(. /etc/os-release && echo "$VERSION_ID")/prod.list" \
        -o /etc/apt/sources.list.d/mssql-release.list
    apt-get update -qq
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev
fi
info "ODBC drivers: $(python3 -c 'import pyodbc; print([d for d in pyodbc.drivers() if "SQL" in d])' 2>/dev/null || echo 'check after venv')"

# ── 9. Initialise database ────────────────────────────────────────────────────
info "Initialising SQL Server schema (and migrating local data if present)..."
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && .venv/bin/python scripts/init_db.py"

# ── 10. Systemd service ────────────────────────────────────────────────────────
info "Installing systemd service..."
install -m 644 "$(dirname "$0")/cobaltax.service" /etc/systemd/system/cobaltax.service
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

# ── 9. Caddy (reverse proxy + automatic HTTPS) ────────────────────────────────
info "Installing Caddy..."
if ! command -v caddy &>/dev/null; then
    apt-get install -y --no-install-recommends debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y caddy
fi

CADDYFILE=/etc/caddy/Caddyfile
info "Writing $CADDYFILE for $DOMAIN..."
cat > "$CADDYFILE" <<EOF
$DOMAIN {
    reverse_proxy 127.0.0.1:8080
    encode gzip

    # Security headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        -Server
    }
}
EOF

systemctl enable caddy
systemctl restart caddy

# ── 10. Firewall (ufw) ────────────────────────────────────────────────────────
if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    info "Opening HTTP/HTTPS in ufw..."
    ufw allow 80/tcp  comment "Caddy HTTP (ACME redirect)"
    ufw allow 443/tcp comment "Caddy HTTPS"
    # 8080 stays closed — only Caddy reaches it via localhost
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo
green "CobaltaX installed and running."
green "  Web UI:  https://$DOMAIN"
green "  Logs:    journalctl -u $SERVICE -f"
green "  Status:  systemctl status $SERVICE"
green "  Data:    $DATA_DIR"
echo
echo "Make sure DNS for $DOMAIN points to this server's public IP before Caddy can obtain a certificate."
echo
echo "Next step — if Telegram is configured, seal the session once:"
echo "  sudo -u $APP_USER bash -c 'cd $APP_DIR && .venv/bin/python scripts/telegram_login.py'"
