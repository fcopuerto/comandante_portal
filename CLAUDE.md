# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

CobaltaX Server Monitor is a professional cross-platform GUI application for monitoring and managing Ubuntu servers on local networks. It features:

- Real-time server status monitoring (ping + SSH connectivity)
- Remote server restart via SSH with passwordless/password-authenticated sudo
- Multilanguage support (English, Spanish, Catalan) with runtime language switching
- Telegram integration for viewing group/channel messages via Telethon
- Multi-user authentication with per-user passwords
- Encrypted SQLite configuration store (no secrets in code/git)
- Audit logging (JSON lines format) for admin review
- PyInstaller packaging for Windows executable distribution

## Build & Run Commands

### Development Setup

```bash
# Create Conda environment
conda env create -f environment.yml
conda activate servers_cobaltax

# OR with pip directly (requires Python 3.11+)
pip install -r requirements.txt
```

### Run the Application

```bash
# Run the GUI directly
python server_monitor.py

# OR use the convenience script (loads .env automatically)
./run.sh
```

### First-Time Telegram Setup

```bash
# Interactively create a user session for Telegram history access
# (required once to authenticate with Telegram)
python scripts/telegram_login.py

# Seal Telegram credentials into encrypted store (removes need for .env at runtime)
python scripts/init_from_env.py
```

### Testing & Debugging

```bash
# Test SSH restart functionality without executing
python test_restart_command.py

# Complete diagnostic tool for restart issues
python debug_restart.py

# Quick Telegram credential check
python scripts/check_telegram_creds.py

# Verify who you're logged in as (Telegram)
python scripts/telegram_whoami.py
```

### Windows EXE Packaging

```bash
# Install PyInstaller first
pip install pyinstaller

# Build executable (creates dist/CobaltaXMonitor/)
pyinstaller pyinstaller.spec

# OR build one-folder (faster startup):
pyinstaller --noconfirm --clean ^
   --name CobaltaXMonitor ^
   --add-data "translations;translations" ^
   --hidden-import telethon --hidden-import cryptography --hidden-import paramiko ^
   main.py

# Reset store for testing (removes DB and cache)
CobaltaXMonitor.exe --reset-store
```

## Architecture & Design Patterns

### Core Layer: Config & Security

**config.py** - Central configuration module:
- Defines server list with SSH credentials (references env vars, not hardcoded)
- Loads multi-user authentication via COBALTAX_USERS + COBALTAX_PASS_<NAME> env vars
- Reads Telegram API credentials (TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_CHAT_ID)
- Detects OS language and maps to supported languages (en/es/ca)

**secure_config_store.py** - Encrypted SQLite storage:
- Stores servers, users, and Telegram settings in `~/.cobaltax/config_store.sqlite`
- Fernet-based symmetric encryption (key stored in `~/.cobaltax/.config_master.key`)
- Provides `load_servers()`, `upsert_server()`, `get_user_password()`, `get_setting()`/`set_setting()`
- Fallback JSON cache (`config_cache.json`) for offline resilience
- Auto-migrates from env vars on startup

**audit_logger.py** - JSON-lines audit trail:
- Logs events to `audit.log` with timestamp, user, event type, and details
- Thread-safe logging with file rotation support
- Session-aware (tracks authenticated user)
- Events: login_success/failed, restart_executed/cancelled, audit_view_opened/denied

### GUI Layer: Tkinter-based Interface

**server_monitor.py** - Main GUI application (large ~2600 lines):
- Inherits config, starts auth dialog if AUTH_ENABLED
- Multi-threaded status polling (ping + SSH port check every 30 seconds)
- Theme system (modern, retro_green, retro_amber, retro_gray)
- Real-time language switching without restart
- Dependency hierarchy support (ESXi parent > child VMs)
- Layout modes: compact/ultra-compact/card-based views
- Telegram message panel (auto-refresh, filter, send)
- Admin-only audit table with filters

Key classes:
- `ServerMonitorGUI` - Main window, event handlers, status refresh loop
- Per-server widgets include: status indicator, IP, OS icon, action buttons
- Uses `async_operation()` for background tasks (prevents UI freeze)

**language_manager.py** - I18n support:
- Loads translations from `translations/{en,es,ca}.json`
- Provides `get_text(key)` and `_()` shorthand function
- Real-time language switching via GUI dropdown

**server_utils.py** - Network and SSH operations:
- `ServerMonitor` class: ping (cross-platform) + SSH port connectivity checks
- `SSHManager` class: wraps Paramiko for SSH execution
  - `create_ssh_client()` - Handles password/key authentication
  - `execute_ssh_command()` - Runs remote command with optional sudo
  - `test_sudo_access()` - Checks for sudo availability
- `TelegramClient` class: legacy HTTP bot API (deprecated, kept for reference)
- Telethon integration wrappers: `telethon_start_background()`, `telethon_fetch_history()`
- `async_operation()` - Decorator for background execution with callback

**telethon_runner.py** - Background Telegram client:
- Runs Telethon in separate asyncio event loop + thread
- Stores session at `~/.cobaltax/cobaltax_user_session(.session)`
- Exposes `get_entity_and_messages()` for synchronous GUI calls
- Loads credentials from secure store first, then env, then globals
- Handles session password prompts transparently

### Entry Point & Packaging

**main.py** - PyInstaller entry point:
- Loads optional portable `.env` file (for first-run convenience)
- Supports `--reset-store` flag for development/support
- Launches GUI via `server_monitor.main()` or direct instantiation

**pyinstaller.spec** - PyInstaller configuration:
- Bundles translations/ directory
- Includes hidden imports: telethon, cryptography, paramiko
- Creates portable Windows executable with persistent user data

## Configuration & Secrets Management

### Environment Variables

Core (set these first):
- `COBALTAX_USERS=Jose,Eva,Abelardo` (multi-user list)
- `COBALTAX_PASS=FallbackPassword` (global or single-user password)
- `COBALTAX_PASS_JOSE=SecretForJose` (per-user override, accents stripped in var name)
- `COBALTAX_ADMINS=Jose` (comma-sep admin list; defaults to first user)

SSH per-server:
- `SSH_PASS_UBUTWO=...` (server-specific password, referenced in config.py)

Telegram:
- `TELEGRAM_API_ID=123456` (integer)
- `TELEGRAM_API_HASH=abcdef...` (hex string, ~34 chars)
- `TELEGRAM_CHAT_ID=-100xxxxxxxxx` (group/channel ID or user ID)
- `TELEGRAM_DEFAULT_LIMIT=50` (optional, default 50 messages)
- `TELEGRAM_REFRESH_INTERVAL=120` (optional, default 120 seconds)

### Workflow: From .env to Encrypted Store

1. Define `.env` or `.env.cobaltax` (not committed) with all secrets
2. On first run, `init_from_env.py` migrates credentials to encrypted SQLite
3. On all subsequent runs, config loads from encrypted store automatically
4. Production deployment: remove `.env` file, keep only `.cobaltax/` directory

Artifacts to protect in production (not committed):
```
.cobaltax/
  config_store.sqlite       (encrypted DB)
  .config_master.key        (Fernet key, chmod 600)
  config_cache.json         (backup encrypted cache)
  cobaltax_user_session(.session)  (Telegram session)
```

## Key Design Decisions

### Security

- **No plaintext secrets in code** - All credentials via env or encrypted store
- **Fernet encryption** - Simple local-first protection (not production-grade for high-security)
- **Per-user password support** - Allows stricter access control (e.g., read-only users vs. admins)
- **Audit trail** - All critical actions logged with user/timestamp for accountability

### Scalability & Offline-First

- **Encrypted JSON cache fallback** - Operates if SQLite DB unavailable (e.g., locked, corrupted)
- **Dependency hierarchy** - ESXi hosts as parents, VMs as children, with cascade visibility
- **Async background polling** - Prevents UI freeze during long SSH/network operations
- **Telethon background thread** - Telegram fetches don't block GUI refresh

### GUI Philosophy

- **Language-agnostic** - All UI strings in `translations/{lang}.json`
- **Theme system** - Retro terminal themes for nostalgia, modern for usability
- **Compact/card modes** - Adapt layout to user preference and screen size
- **Hierarchical view** - Group servers by parent (ESXi), hide/show children

### Extensibility

- **AWS sync phase planned** - Infrastructure scaffold in `infra/` (Lambda, DynamoDB, API Gateway)
- **Settings table in secure store** - Extensible for future app configuration
- **Lambda audit batch endpoint** - Planned for periodic sync of audit logs to cloud

## Important Directories & Files

```
translations/             # i18n JSON files (en.json, es.json, ca.json)
infra/                    # AWS deployment scaffold (not yet active)
scripts/                  # Helper utilities
  - telegram_login.py     # Create Telegram user session (interactive)
  - telegram_whoami.py    # Test Telegram auth
  - check_telegram_creds.py
  - init_from_env.py      # Seal env vars to encrypted store
  - test.py               # Quick Telegram message fetch test
```

## Common Development Tasks

### Adding a New Server

Edit `config.py` and add to SERVERS list, or use `init_from_env.py` to migrate from env var, or use runtime Python shell:

```python
from secure_config_store import upsert_server
upsert_server('myserver.local', '192.168.1.200', 'admin', 'SSH_PASS_MYSERVER', 22, 'linux')
```

### Adding UI Strings for Multilanguage

1. Edit `translations/{en,es,ca}.json` with new key-value pairs
2. Use `_('key_name')` in Python code (imported from language_manager)
3. Changes apply immediately without restart

### Debugging SSH Issues

Use `debug_restart.py` which tests:
1. Ping connectivity
2. SSH port open
3. SSH login success
4. Sudo access (passwordless vs. password-protected)
5. Restart command construction

If "all restart commands failed", check:
- Server SSH service running
- Firewall not blocking port 22
- SSH user is in sudoers (or `NOPASSWD:` configured)

### Troubleshooting Telegram Integration

- **"Telegram credentials not found"** - Provide TELEGRAM_API_ID/HASH/CHAT_ID via .env or secure store
- **"Need to login"** - Run `python scripts/telegram_login.py` to create session
- **"No messages fetched"** - Verify TELEGRAM_CHAT_ID is correct (use `telegram_whoami.py` to list dialogs)
- **"Session expired"** - Delete `~/.cobaltax/cobaltax_user_session.session` and re-login

## Testing & Quality

- No unit test framework configured yet (TODO)
- Manual testing via GUI recommended
- Use `test_restart_command.py` before enabling restart in production
- CI/CD pipeline not yet configured (AWS Lambda tests in `infra/lambdas/` are standalone)

## Git Workflow & Tags

Current version tagged as **v1-offline-local** (baseline before AWS sync):

```bash
git tag -l                    # List all tags
git show v1-offline-local     # View baseline version
```

AWS sync development planned on new branch (aws-sync).

## Environment Detection

- Automatically detects OS language (locale) and maps to en/es/ca
- Falls back to Spanish (es) if unknown language
- Can be overridden by `DEFAULT_LANGUAGE` in config.py or GUI dropdown
