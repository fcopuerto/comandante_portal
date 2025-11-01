"""Background Telethon runner to allow Tkinter GUI to call Telethon synchronously.

This module starts a TelegramClient in a dedicated asyncio loop running in a
background thread. The GUI can then schedule coroutines on that loop using
run_coroutine_threadsafe and block briefly for results.

It stores the session file under the per-user data dir `~/.cobaltax/cobaltax_user_session`.
"""
from __future__ import annotations

import asyncio
import threading
import os
import time
from typing import Optional, Tuple, Any, List

try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    _HAS_TELETHON = True
except Exception:
    _HAS_TELETHON = False


# Use the same per-user base as secure_config_store
_USER_BASE = os.path.join(os.path.expanduser('~'), '.cobaltax')
_SESSION_BASENAME = os.environ.get('COBALTAX_TELETHON_SESSION', os.path.join(_USER_BASE, 'cobaltax_user_session'))

_client: Optional[TelegramClient] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread] = None


def _get_credentials() -> Tuple[Optional[int], Optional[str]]:
    """Return (api_id, api_hash) from environment or None."""
    api_id = os.environ.get('TELEGRAM_API_ID')
    api_hash = os.environ.get('TELEGRAM_API_HASH')
    try:
        return (int(api_id), api_hash) if api_id and api_hash else (None, None)
    except Exception:
        return (None, api_hash)


def start_telethon_background(timeout: float = 5.0) -> Tuple[Optional[TelegramClient], Optional[asyncio.AbstractEventLoop]]:
    """Start the Telethon client in a background thread and return (client, loop).

    Raises RuntimeError if Telethon is not available or credentials missing.
    Blocks briefly (up to `timeout`) waiting for client to be ready.
    """
    global _client, _loop, _thread
    if not _HAS_TELETHON:
        raise RuntimeError('telethon is not installed')
    if _client is not None and _loop is not None:
        return _client, _loop

    api_id, api_hash = _get_credentials()
    if not api_id or not api_hash:
        raise RuntimeError('Missing TELEGRAM_API_ID/TELEGRAM_API_HASH')

    def _runner():
        nonlocal api_id, api_hash
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = TelegramClient(_SESSION_BASENAME, api_id, api_hash)
        loop.run_until_complete(client.start())
        # expose
        globals()['_client'] = client
        globals()['_loop'] = loop
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(client.disconnect())
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass

    _thread = threading.Thread(target=_runner, daemon=True)
    _thread.start()

    # wait for startup
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _client is not None and _loop is not None:
            return _client, _loop
        time.sleep(0.05)

    raise RuntimeError('Timed out waiting for Telethon client to start')


def stop_telethon_background():
    """Stop the background Telethon loop and client."""
    global _client, _loop
    if _loop is None:
        return
    try:
        _loop.call_soon_threadsafe(_loop.stop)
    except Exception:
        pass
    _client = None
    _loop = None


def get_entity_and_messages(chat_id: Any, limit: int = 50, timeout: float = 10.0) -> Tuple[Optional[Any], List[Any]]:
    """Resolve entity and fetch recent messages synchronously for the GUI.

    chat_id may be an int or the Bot-API style id string (-100...), or username.
    Returns (entity, [messages]) or (None, []).
    """
    global _client, _loop
    if not _HAS_TELETHON:
        raise RuntimeError('telethon is not installed')

    if _client is None or _loop is None:
        start_telethon_background()

    # schedule coroutines
    from concurrent.futures import TimeoutError as FutTimeout
    fut_ent = asyncio.run_coroutine_threadsafe(_client.get_entity(chat_id), _loop)
    try:
        ent = fut_ent.result(timeout=timeout)
    except Exception:
        ent = None
    if ent is None:
        # Try to match by iterating dialogs (handles -100 prefix matching)
        fut_iter = asyncio.run_coroutine_threadsafe(_client.get_dialogs(limit=200), _loop)
        try:
            dialogs = fut_iter.result(timeout=timeout)
        except Exception:
            dialogs = []
        matched = None
        for d in dialogs:
            ent2 = d.entity
            base_id = getattr(ent2, 'id', None)
            if base_id is None:
                continue
            full_id = f"-100{base_id}" if ent2.__class__.__name__ == 'Channel' else str(base_id)
            if str(full_id) == str(chat_id) or str(base_id) == str(chat_id):
                matched = ent2
                break
        ent = matched

    msgs = []
    if ent is not None:
        fut_msgs = asyncio.run_coroutine_threadsafe(_client.get_messages(ent, limit=limit), _loop)
        try:
            msgs = fut_msgs.result(timeout=timeout)
        except Exception:
            msgs = []
    return ent, list(msgs)
