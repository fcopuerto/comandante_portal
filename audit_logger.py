import os
import json
import threading
import datetime
from typing import Optional, Dict, Any

_LOG_LOCK = threading.Lock()

AUDIT_LOG_PATH = os.environ.get('COBALTAX_AUDIT_FILE', 'audit.log')

_session_user: Optional[str] = None


def set_session_user(user: str):
    global _session_user
    _session_user = user


def get_session_user() -> Optional[str]:
    return _session_user


def _serialize(obj: Any):
    if isinstance(obj, (list, dict, str, int, float, type(None))):
        return obj
    return str(obj)


def log_event(event: str, details: Optional[Dict[str, Any]] = None):
    record = {
        'ts': datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z',
        'user': _session_user,
        'event': event,
        'details': {k: _serialize(v) for k, v in (details or {}).items()}
    }
    line = json.dumps(record, ensure_ascii=False)
    with _LOG_LOCK:
        with open(AUDIT_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')


def rotate_if_needed(max_bytes: int = 1_000_000, keep: int = 3):
    try:
        if not os.path.exists(AUDIT_LOG_PATH):
            return
        size = os.path.getsize(AUDIT_LOG_PATH)
        if size < max_bytes:
            return
        base = AUDIT_LOG_PATH
        # Rotate
        for i in range(keep - 1, 0, -1):
            older = f"{base}.{i}"
            newer = f"{base}.{i+1}"
            if os.path.exists(older):
                os.replace(older, newer)
        os.replace(base, f"{base}.1")
    except Exception:
        pass
