# Configuration file for server monitoring
# Edit this file to add your Ubuntu servers

import unicodedata as _unicodedata
import os
SERVERS = [
    {
        'name': 'ubutwo.cobaltax.local',
        'ip': '192.168.23.42',  # Replace with your server's IP
        'ssh_user': 'administrador',  # Replace with your SSH username
        # Replace with your SSH password (or None if using key)
        'ssh_password': 'REDACTED',
        'ssh_key_path': None,  # Path to SSH private key (optional)
        'ssh_port': 22,  # SSH port (default is 22)
        'os_type': 'linux',  # Options: 'linux', 'windows', 'esxi'
        # Optional: parent host IP if this VM/container lives inside another host (e.g. ESXi)
        'parent': '192.168.23.49'
    },
    {
        'name': 'ubuntuserver.cobaltax.local',
        'ip': '192.168.23.50',  # Replace with your server's IP
        'ssh_user': 'administrador',  # Replace with your SSH username
        # Replace with your SSH password (or None if using key)
        'ssh_password': 'REDACTED',
        'ssh_key_path': None,  # Path to SSH private key (optional)
        'ssh_port': 22,  # SSH port (default is 22)
        'os_type': 'linux',
        'parent': '192.168.23.49'
    },
    # Example Windows Server configuration
    {
        'name': 'WIN-K781E2RUC5K.cobaltax.local (MURANO)',
        'ip': '192.168.23.139',
        'ssh_user': 'Administrador',  # Windows SSH username
        'ssh_password': 'REDACTED',
        'ssh_key_path': None,
        'ssh_port': 22,  # OpenSSH port on Windows
        'os_type': 'windows'
    },
    # Example ESXi 5.1 host configuration (requires pyvmomi and direct host access)
    # For ESXi: use 'ssh_user'/'ssh_password' for the ESXi root or admin user
    # 'ssh_port' is typically 22; 'os_type': 'esxi'
    {
        'name': 'esxi-host.local',
        'ip': '192.168.23.49',
        'ssh_user': 'root',
        'ssh_password': 'REDACTED',
        'ssh_key_path': None,
        'ssh_port': 22,
        'os_type': 'esxi'
    }
]

# Monitoring settings
PING_TIMEOUT = 3  # Timeout for ping in seconds
REFRESH_INTERVAL = 30  # Auto-refresh interval in seconds
SSH_TIMEOUT = 10  # SSH connection timeout in seconds

# GUI settings
WINDOW_TITLE = "Cobaltax Server Monitor"
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 400
# Options: 'modern', 'retro_green', 'retro_amber', 'retro_gray'
DEFAULT_THEME = 'modern'

# Language settings
# Options: 'en' (English), 'es' (Spanish), 'ca' (Catalan)
DEFAULT_LANGUAGE = 'en'

"""Telegram configuration.

We now use ONLY a Telethon user session (no Bot API). Supply credentials via env vars:
    export TELEGRAM_API_ID=123456
    export TELEGRAM_API_HASH=abcdef123456...
    export TELEGRAM_CHAT_ID=-100xxxxxxxxx   # group/channel or user id

Create/login session (once):
    python scripts/telegram_login.py

The previous hard‑coded bot token has been removed to avoid leaking secrets.
"""

# Removed legacy bot token usage; keep variable for backward compatibility if code checks it
TELEGRAM_TOKEN = None

# Chat ID still required for sending / fetching history
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# Telethon credentials (must be provided via environment for security)
TELEGRAM_API_ID = os.environ.get('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.environ.get(
    'TELEGRAM_API_HASH', 'REDACTED')

# Feature flag indicating whether Telegram features should appear in UI
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')  # no default
TELEGRAM_ENABLED = bool(
    TELEGRAM_CHAT_ID and TELEGRAM_API_ID and TELEGRAM_API_HASH)

# Default Telegram fetch limit and auto-refresh interval (seconds)
TELEGRAM_DEFAULT_LIMIT = int(os.environ.get('TELEGRAM_DEFAULT_LIMIT', '50'))
TELEGRAM_REFRESH_INTERVAL = int(
    os.environ.get('TELEGRAM_REFRESH_INTERVAL', '120'))

# --- Authentication (single or multi-user) ---
# Legacy single-user: set COBALTAX_USER and COBALTAX_PASS
AUTH_USERNAME = os.environ.get('COBALTAX_USER')
# global password or legacy single-user password
AUTH_PASSWORD = os.environ.get('COBALTAX_PASS')

# Multi-user list: if COBALTAX_USERS unset, fall back to provided static list from request.
AUTH_USERS_RAW = os.environ.get('COBALTAX_USERS')
if AUTH_USERS_RAW:
    AUTH_USERS = [u.strip() for u in AUTH_USERS_RAW.split(',') if u.strip()]
else:
    AUTH_USERS = ['Jose', 'Eva', 'Abelardo', 'Mario', 'Llorenç', 'Fran']

# Per-user passwords: environment variables COBALTAX_PASS_<UPPER_NAME>
# Accents are stripped for variable naming (e.g., Llorenç -> LLORENC)


def _norm_name_for_env(n: str) -> str:
    nf = _unicodedata.normalize('NFD', n)
    base = ''.join(ch for ch in nf if _unicodedata.category(ch) != 'Mn')
    return base.upper().replace(' ', '_')


AUTH_PASSWORDS = {}
for _u in AUTH_USERS:
    env_key = f"COBALTAX_PASS_{_norm_name_for_env(_u)}"
    val = os.environ.get(env_key)
    if val:
        AUTH_PASSWORDS[_u] = val

# Auth is enabled if:
#  - Legacy single-user creds provided, OR
#  - Multi-user list present AND (global password or at least one per-user password)
AUTH_ENABLED = False
if AUTH_USERNAME and AUTH_PASSWORD:
    AUTH_ENABLED = True
elif AUTH_USERS and (AUTH_PASSWORD or AUTH_PASSWORDS):
    AUTH_ENABLED = True

# --- Admin users (allowed to view audit log) ---
# Comma separated list via COBALTAX_ADMINS, else default to first user (if any)
_admins_raw = os.environ.get('COBALTAX_ADMINS')
if _admins_raw:
    ADMIN_USERS = [u.strip() for u in _admins_raw.split(',') if u.strip()]
else:
    ADMIN_USERS = [AUTH_USERS[0]] if AUTH_USERS else []
