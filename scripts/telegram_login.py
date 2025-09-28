#!/usr/bin/env python3
"""Interactive helper to create a user session for full Telegram history.

Usage:
  1. Ensure you have set environment variables TELEGRAM_API_ID and TELEGRAM_API_HASH.
     (export TELEGRAM_API_ID=123456 export TELEGRAM_API_HASH=abcdef123456...)
  2. Run: python scripts/telegram_login.py
  3. Follow the prompts (phone number, login code, 2FA password if enabled).
  4. A session file ~/.cobaltax_user_session(.session) will be created.
  5. Then from the GUI, use the 'Full History' button to load full group/channel history.

This uses your USER account (not the bot) giving access to complete history
according to your normal Telegram permissions. Keep the resulting session file
secure. Delete it if you no longer need the functionality.
"""
import os
import sys

try:
    from telethon.sync import TelegramClient  # type: ignore
except Exception:
    print("telethon not installed. Install with: pip install telethon")
    sys.exit(1)

API_ID = os.environ.get('TELEGRAM_API_ID')
API_HASH = os.environ.get('TELEGRAM_API_HASH')
if not API_ID or not API_HASH:
    print("Please set TELEGRAM_API_ID and TELEGRAM_API_HASH in your environment.")
    sys.exit(1)

try:
    API_ID_INT = int(API_ID)
except Exception:
    print(f"Invalid TELEGRAM_API_ID: {API_ID}")
    sys.exit(1)

SESSION_PATH = os.path.join(os.path.expanduser('~'), '.cobaltax_user_session')
print(f"Using session path: {SESSION_PATH}.session")

with TelegramClient(SESSION_PATH, API_ID_INT, API_HASH) as client:
    if not client.is_user_authorized():
        phone = input(
            "Enter your phone number (with country code, e.g. +1555123456): ").strip()
        client.send_code_request(phone)
        code = input("Enter the login code you received: ").strip()
        try:
            client.sign_in(phone=phone, code=code)
        except Exception as e:
            # 2FA password maybe required
            if 'password' in str(e).lower():
                pw = input("Two-step password: ")
                client.sign_in(password=pw)
            else:
                print(f"Login failed: {e}")
                sys.exit(1)
    me = client.get_me()
    print(
        f"Logged in as: {getattr(me, 'username', None) or me.first_name} (id={me.id})")
    print("Session created. You can now use full history in the GUI.")
