# Configuration file for server monitoring
# Edit this file to add your Ubuntu servers

import unicodedata as _unicodedata
import os
""" IMPORTANT SECURITY NOTE
Plaintext credentials have been removed from this file.
Provide sensitive values via environment variables or a .env file (not committed) such as:

  SSH_PASS_SERVER1=...   TELEGRAM_API_ID=...   COBALTAX_PASS=...

Each server below can reference an env var holding the password. If you rely on SSH keys,
leave 'ssh_password_env' as None and set 'ssh_key_path'.
"""

SERVERS = [
    # --- Cobaltax Principal (192.168.23.0/24) — Servers ---
    {
        'name': 'esxi-host.local',
        'ip': '192.168.23.49',
        'ssh_user': 'root',
        'ssh_password_env': 'SSH_PASS_ESXI',
        'ssh_key_path': None,
        'ssh_port': 22,
        'os_type': 'esxi',
        'subnet': 'cobaltax_main',
        'watts_idle': 40,   # PowerEdge T20 (Xeon E3-1200 v3, desktop-class, very efficient)
        'watts_max': 130,
    },
    {
        'name': 'ubutwo.cobaltax.local',
        'ip': '192.168.23.42',
        'ssh_user': 'administrador',
        'ssh_password_env': 'SSH_PASS_UBUTWO',
        'ssh_key_path': None,
        'ssh_port': 22,
        'os_type': 'linux',
        'parent': '192.168.23.49',
        'subnet': 'cobaltax_main',
        'watts_idle': 0, 'watts_max': 0,  # VM inside ESXi T20 — power counted in host
    },
    {
        'name': 'ubuntuserver.cobaltax.local',
        'ip': '192.168.23.50',
        'ssh_user': 'administrador',
        'ssh_password_env': 'SSH_PASS_UBUNTUSERVER',
        'ssh_key_path': None,
        'ssh_port': 22,
        'os_type': 'linux',
        'parent': '192.168.23.49',
        'subnet': 'cobaltax_main',
        'watts_idle': 0, 'watts_max': 0,  # VM inside ESXi T20 — power counted in host
    },
    {
        'name': 'Windows PC (192.168.23.48)',
        'ip': '192.168.23.48',
        'ssh_user': None,
        'ssh_password_env': None,
        'ssh_key_path': None,
        'ssh_port': None,
        'os_type': 'windows',
        'subnet': 'cobaltax_main',
    },
    {
        'name': 'WIN-K781E2RUC5K.cobaltax.local (MURANO)',
        'ip': '192.168.23.139',
        'ssh_user': 'Administrador',
        'ssh_password_env': 'SSH_PASS_MURANO',
        'ssh_key_path': None,
        'ssh_port': 22,
        'os_type': 'windows',
        'subnet': 'cobaltax_main',
        'watts_idle': 65,   # PowerEdge R240
        'watts_max': 175,
    },
    {
        'name': 'ciserver.cobaltax.local',
        'ip': '192.168.23.201',
        'ssh_user': 'root',
        'ssh_password_env': 'SSH_PASS_CISERVER',
        'ssh_key_path': None,
        'ssh_port': 22,
        'os_type': 'synology',
        'subnet': 'cobaltax_main',
        'watts_idle': 25,   # HP MicroServer Gen8 G1610T (Celeron 35W TDP, very efficient)
        'watts_max': 65,
    },
    # --- Cobaltax Principal — Network Devices ---
    {
        'name': 'Orange Router (Gateway)',
        'ip': '192.168.23.200',
        'ssh_user': None,
        'ssh_password_env': None,
        'ssh_key_path': None,
        'ssh_port': None,
        'os_type': 'router',
        'subnet': 'cobaltax_main',
        'web_url': 'http://192.168.23.200/',
    },
    {
        'name': 'Ciagrei AP',
        'ip': '192.168.23.199',
        'ssh_user': None,
        'ssh_password_env': None,
        'ssh_key_path': None,
        'ssh_port': None,
        'os_type': 'ap',
        'subnet': 'cobaltax_main',
        'web_url': 'http://192.168.23.199/',
    },
    # --- Cobaltax Tienda (192.168.9.0/24) — Network Devices ---
    {
        'name': 'Router Tienda',
        'ip': '192.168.9.1',
        'ssh_user': None,
        'ssh_password_env': None,
        'ssh_key_path': None,
        'ssh_port': None,
        'os_type': 'router',
        'subnet': 'cobaltax_tienda',
        'web_url': 'http://192.168.9.1/',
    },
]

# Monitoring settings
PING_TIMEOUT = 3  # Timeout for ping in seconds
REFRESH_INTERVAL = 30  # Auto-refresh interval in seconds
SSH_TIMEOUT = 10  # SSH connection timeout in seconds
# Additional SSH handshake tuning
SSH_BANNER_TIMEOUT = int(os.environ.get('SSH_BANNER_TIMEOUT', '10'))  # time to wait for SSH banner
SSH_AUTH_TIMEOUT = int(os.environ.get('SSH_AUTH_TIMEOUT', '10'))      # time to wait for auth response

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
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')  # single assignment

# Telethon credentials (must be provided via environment OR sealed in secure store)
TELEGRAM_API_ID = os.environ.get('TELEGRAM_API_ID')
# Do NOT provide a default hash here; forcing explicit provisioning or secure-store load
TELEGRAM_API_HASH = os.environ.get('TELEGRAM_API_HASH')

# Feature flag indicating whether Telegram features should appear in UI at import time.
# (May be recomputed later after secure store override.)
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
