#!/usr/bin/env python3
"""CobaltaX Server Monitor — FastAPI web backend (replaces server_monitor.py)."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import secrets
import select
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import chat_db
import ldap_auth
import modules as portal_modules
import support_db
import wiki_db

from config import (
    SERVERS, PING_TIMEOUT, REFRESH_INTERVAL, SSH_TIMEOUT,
    SSH_BANNER_TIMEOUT, SSH_AUTH_TIMEOUT,
    TELEGRAM_ENABLED, TELEGRAM_CHAT_ID, TELEGRAM_TOKEN,
    AUTH_ENABLED, AUTH_PASSWORD, AUTH_USERS, AUTH_PASSWORDS,
    ADMIN_USERS, DEFAULT_LANGUAGE,
    TELEGRAM_DEFAULT_LIMIT,
)
from server_utils import ServerMonitor, SSHManager
from audit_logger import log_event, set_session_user, AUDIT_LOG_PATH

# --- Secure config store (optional) ---
try:
    from secure_config_store import (
        init_db as _secure_init_db,
        load_servers as _secure_load_servers,
        get_user_password as _secure_get_user_password,
        get_setting as _secure_get_setting,
        set_setting as _secure_set_setting,
        is_admin as _secure_is_admin,
        list_users as _secure_list_users,
    )
    _secure_init_db(migrate=True)
    _db_servers = _secure_load_servers()
    if _db_servers:
        # Build a lookup of config.py servers by IP to recover extra fields
        from config import SERVERS as _cfg_servers
        _cfg_by_ip = {s['ip']: s for s in _cfg_servers}
        for _s in _db_servers:
            _cfg = _cfg_by_ip.get(_s['ip'], {})
            if not _s.get('ssh_password') and not _s.get('ssh_password_env'):
                _env_key = _cfg.get('ssh_password_env')
                if _env_key:
                    _s['ssh_password_env'] = _env_key
            # Always prefer config.py for these fields (DB may have stale/default values)
            for _field in ('os_type', 'subnet', 'web_url', 'parent',
                           'watts_idle', 'watts_max'):
                if _cfg.get(_field) is not None:
                    _s[_field] = _cfg[_field]
        # Include config.py-only entries not in DB (e.g., routers without SSH)
        _db_ips = {s['ip'] for s in _db_servers}
        for _cfg_s in _cfg_servers:
            if _cfg_s['ip'] not in _db_ips:
                _db_servers.append(dict(_cfg_s))
        SERVERS.clear()
        SERVERS.extend(_db_servers)
    for _k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_CHAT_ID"):
        _v = _secure_get_setting(_k)
        if _v:
            os.environ.setdefault(_k, str(_v))
    if all(os.environ.get(k) for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_CHAT_ID")):
        TELEGRAM_ENABLED = True
except Exception as _e:
    print(f"Secure config store: {_e}")
    _secure_get_user_password = None  # type: ignore
    _secure_is_admin = None           # type: ignore
    _secure_list_users = None         # type: ignore

# --- Session store ---
_sessions: Dict[str, Dict[str, Any]] = {}
_SESSION_COOKIE = "cobaltax_session"
_SESSION_TTL = 8 * 3600  # 8 hours


def _reload_servers_list() -> None:
    """Reload SERVERS from encrypted store, preserving config.py-only entries."""
    try:
        from secure_config_store import load_servers as _ls
        db_servers = _ls()
        from config import SERVERS as _cfg
        cfg_by_ip = {s['ip']: s for s in _cfg}
        for s in db_servers:
            cfg = cfg_by_ip.get(s['ip'], {})
            for field in ('subnet', 'web_url', 'parent', 'watts_idle', 'watts_max'):
                if s.get(field) is None and cfg.get(field) is not None:
                    s[field] = cfg[field]
        db_ips = {s['ip'] for s in db_servers}
        for cs in _cfg:
            if cs['ip'] not in db_ips:
                db_servers.append(dict(cs))
        SERVERS.clear()
        SERVERS.extend(db_servers)
    except Exception as e:
        print(f"[reload_servers] {e}")


def _new_session(user: str, is_admin: bool, groups: List[str] = None, permissions: Dict[str, str] = None) -> str:
    token = secrets.token_hex(32)
    _sessions[token] = {
        "user": user,
        "is_admin": is_admin,
        "groups": groups or [],
        "permissions": permissions or ({"health": "admin"} if is_admin else {}),
        "ts": time.time(),
    }
    return token


def _get_session(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get(_SESSION_COOKIE)
    if not token:
        return None
    sess = _sessions.get(token)
    if not sess or time.time() - sess["ts"] > _SESSION_TTL:
        _sessions.pop(token, None)
        return None
    return sess


def _require_session(request: Request) -> Dict[str, Any]:
    sess = _get_session(request)
    if not sess:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return sess


def _require_admin(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not sess.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin required")
    return sess


# --- Server status cache ---
_server_status: Dict[str, Dict[str, Any]] = {}
_server_monitor = ServerMonitor(timeout=PING_TIMEOUT)
_ssh_manager = SSHManager(
    timeout=SSH_TIMEOUT,
    banner_timeout=SSH_BANNER_TIMEOUT,
    auth_timeout=SSH_AUTH_TIMEOUT,
)

# SSE: per-client asyncio queues
_sse_subscribers: List[asyncio.Queue] = []
_sse_loop: Optional[asyncio.AbstractEventLoop] = None


def _broadcast(data: Dict[str, Any]) -> None:
    if _sse_loop is None:
        return
    payload = json.dumps(data, default=str)
    for q in list(_sse_subscribers):
        try:
            _sse_loop.call_soon_threadsafe(q.put_nowait, payload)
        except Exception:
            pass


# --- Energy estimation ---

_ENERGY_WATTAGE: Dict[str, Dict[str, float]] = {
    'esxi':     {'idle': 150, 'max': 400},
    'linux':    {'idle': 25,  'max': 100},
    'windows':  {'idle': 80,  'max': 200},
    'synology': {'idle': 30,  'max': 60},
    'router':   {'idle': 10,  'max': 20},
    'ap':       {'idle': 5,   'max': 15},
}
_ENERGY_DEFAULT_PROFILE = {'idle': 30, 'max': 100}
_ENERGY_PRICE_DEFAULT   = 0.20   # €/kWh
_ENERGY_MAX_READINGS    = 86400  # 30 days at 30 s intervals
def _energy_db_init() -> None:
    from db import get_conn
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            IF OBJECT_ID('cobaltax_energy_readings', 'U') IS NULL
            BEGIN
                CREATE TABLE cobaltax_energy_readings (
                    ip    NVARCHAR(50) NOT NULL,
                    ts    FLOAT        NOT NULL,
                    watts FLOAT        NOT NULL
                );
                CREATE INDEX idx_er_ip_ts ON cobaltax_energy_readings(ip, ts);
            END
        """)


def _energy_load_history() -> None:
    try:
        from db import get_conn
        cutoff = time.time() - 30 * 24 * 3600
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT ip, ts, watts FROM cobaltax_energy_readings WHERE ts >= ? ORDER BY ts",
                cutoff,
            )
            rows = cur.fetchall()
        for ip, ts, watts in rows:
            if ip not in _energy_history:
                _energy_history[ip] = deque(maxlen=_ENERGY_MAX_READINGS)
            _energy_history[ip].append((ts, watts))
        if rows:
            print(f"[energy] Loaded {len(rows)} readings from SQL Server.")
    except Exception as e:
        print(f"[energy] Could not load history: {e}")


def _energy_save_reading(ip: str, ts: float, watts: float) -> None:
    try:
        from db import get_conn
        cutoff = ts - 30 * 24 * 3600
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO cobaltax_energy_readings(ip, ts, watts) VALUES(?,?,?)",
                ip, ts, watts,
            )
            cur.execute(
                "DELETE FROM cobaltax_energy_readings WHERE ts < ?", cutoff,
            )
    except Exception as e:
        print(f"[energy] Save failed: {e}")
_energy_history: Dict[str, deque] = {}


def _estimate_watts(server: Dict[str, Any], status: Dict[str, Any]) -> Optional[float]:
    if not status.get('ping'):
        return 0.0
    # Per-server override takes precedence over os_type profile
    if server.get('watts_idle') is not None and server.get('watts_max') is not None:
        idle, max_w = float(server['watts_idle']), float(server['watts_max'])
    else:
        profile = _ENERGY_WATTAGE.get(server.get('os_type', ''), _ENERGY_DEFAULT_PROFILE)
        idle, max_w = profile['idle'], profile['max']
    resources = status.get('resources') or {}
    cpu = resources.get('cpu_percent')
    if cpu is not None:
        try:
            return round(idle + (max_w - idle) * float(cpu) / 100, 1)
        except (TypeError, ValueError):
            pass
    return round((idle + max_w) / 2, 1) if status.get('online') else 0.0


def _get_energy_price() -> float:
    try:
        if _secure_get_setting:
            val = _secure_get_setting('energy_price_kwh')
            if val:
                return float(val)
    except Exception:
        pass
    return _ENERGY_PRICE_DEFAULT


def _energy_summary(ip: str, now: float) -> Dict[str, Any]:
    history = list(_energy_history.get(ip, []))
    oldest_ts = history[0][0] if history else now
    data_age  = now - oldest_ts  # seconds of history we actually have
    periods: Dict[str, Any] = {}
    for label, seconds in (('1h', 3600), ('24h', 86400), ('7d', 604800), ('30d', 2592000)):
        cutoff   = now - seconds
        readings = [w for ts, w in history if ts >= cutoff]
        kwh      = sum(readings) * REFRESH_INTERVAL / 3_600_000 if readings else 0.0
        coverage = min(data_age, seconds) / seconds  # 0..1
        periods[label] = {'kwh': round(kwh, 4), 'coverage': round(coverage, 3)}
    last = history[-1][1] if history else None
    return {'current_watts': last, 'periods': periods}


def _poll_servers() -> None:
    while True:
        for server in list(SERVERS):
            try:
                status = _server_monitor.get_server_status(server)
                watts = _estimate_watts(server, status)
                ip = server["ip"]
                if ip not in _energy_history:
                    _energy_history[ip] = deque(maxlen=_ENERGY_MAX_READINGS)
                reading_ts = time.time()
                reading_w  = watts or 0.0
                _energy_history[ip].append((reading_ts, reading_w))
                _energy_save_reading(ip, reading_ts, reading_w)
                status.update({"ip": ip, "name": server["name"],
                               "os_type": server.get("os_type", "linux"),
                               "parent": server.get("parent"),
                               "subnet": server.get("subnet"),
                               "web_url": server.get("web_url"),
                               "watts": watts})
                _server_status[ip] = status
                _broadcast({"type": "status", "server": status})
            except Exception as exc:
                print(f"Poll error {server.get('ip')}: {exc}")
        time.sleep(REFRESH_INTERVAL)


# --- FastAPI app ---
_static_dir = pathlib.Path(__file__).parent / "static"

app = FastAPI(title="CobaltaX Server Monitor", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def _startup() -> None:
    global _sse_loop
    _sse_loop = asyncio.get_event_loop()
    try:
        _energy_db_init()
        _energy_load_history()
    except Exception as _e:
        print(f"Warning: energy history DB unavailable ({_e}).")
    threading.Thread(target=_poll_servers, daemon=True).start()
    try:
        support_db.init_db()
        support_db.init_vpn_table()
        support_db.init_workstations_tables()
    except Exception as _e:
        print(f"Warning: support DB unavailable ({_e}). Support ticket features disabled.")
    wiki_db.init_wiki()
    try:
        chat_db.init_db()
    except Exception as _e:
        print(f"Warning: chat history DB unavailable ({_e}).")


app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

_data_dir = pathlib.Path(__file__).parent / "data"
_data_dir.mkdir(exist_ok=True)
app.mount("/data", StaticFiles(directory=str(_data_dir)), name="data")


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> HTMLResponse:
    return HTMLResponse((_static_dir / "index.html").read_text())


@app.get("/sw.js")
async def serve_sw() -> Response:
    content = (_static_dir / "service-worker.js").read_text()
    return Response(content, media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


# --- Auth ---

def _resolve_password(username: str) -> Optional[str]:
    if _secure_get_user_password:
        try:
            pw = _secure_get_user_password(username)
            if pw:
                return pw
        except Exception:
            pass
    pw = AUTH_PASSWORDS.get(username)
    if not pw:
        pw = next((v for k, v in AUTH_PASSWORDS.items() if k.lower() == username.lower()), None)
    return pw or AUTH_PASSWORD


@app.post("/api/auth/login")
async def login(request: Request, response: Response) -> Dict[str, Any]:
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not AUTH_ENABLED:
        token = _new_session(username or "admin", True)
        perms = _sessions[token]["permissions"]
        response.set_cookie(_SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=_SESSION_TTL)
        log_event("login_success", {"user": username or "admin"})
        return {"ok": True, "user": username or "admin", "is_admin": True, "permissions": perms}

    # --- 1. Try LDAP / Active Directory ---
    if ldap_auth.LDAP_ENABLED and username and password:
        ok, ad_groups, err = ldap_auth.authenticate(username, password)
        if ok:
            perms = portal_modules.resolve_permissions(ad_groups)
            is_admin = (
                portal_modules.portal_admin_group().lower() in {g.lower() for g in ad_groups}
                or ldap_auth._ADMIN_GROUP.lower() in {g.lower() for g in ad_groups}
                or any(u.lower() == username.lower() for u in ADMIN_USERS)
            )
            # Portal admins / AD admins get full access to all modules
            if is_admin and not perms:
                perms = {m["id"]: "admin" for m in portal_modules.BUILTIN_MODULES}
            token = _new_session(username, is_admin, ad_groups, perms)
            set_session_user(username)
            response.set_cookie(_SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=_SESSION_TTL)
            log_event("login_success", {"user": username, "method": "ldap", "groups": ad_groups})
            return {"ok": True, "user": username, "is_admin": is_admin, "permissions": perms}
        # Fall through to local auth for any LDAP failure (unreachable or bad creds).
        # Local auth is the final arbiter — it will reject if password is also wrong locally.
        print(f"LDAP auth failed ({err}), falling back to local auth")

    # --- 2. Local password fallback ---
    # Resolve canonical username (case-insensitive) so 'fran' matches 'Fran' in AUTH_USERS
    canonical = next((u for u in AUTH_USERS if u.lower() == username.lower()), username)
    expected = _resolve_password(canonical)
    if not expected or password != expected:
        log_event("login_failed", {"user": username, "method": "local"})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    is_admin = canonical in ADMIN_USERS
    username = canonical  # use canonical name in session/audit
    # Local users get full health access by default
    perms = {m["id"]: ("admin" if is_admin else "view") for m in portal_modules.BUILTIN_MODULES}
    token = _new_session(username, is_admin, [], perms)
    set_session_user(username)
    response.set_cookie(_SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=_SESSION_TTL)
    log_event("login_success", {"user": username, "method": "local"})
    return {"ok": True, "user": username, "is_admin": is_admin, "permissions": perms}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> Dict[str, Any]:
    token = request.cookies.get(_SESSION_COOKIE)
    if token:
        _sessions.pop(token, None)
    response.delete_cookie(_SESSION_COOKIE)
    return {"ok": True}


@app.post("/api/auth/test-ldap")
async def test_ldap(request: Request) -> Dict[str, Any]:
    """Admin-only: test AD credentials and return raw groups + connection diagnostics."""
    _require_admin(request)
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    config_info = {
        "ldap_enabled": ldap_auth.LDAP_ENABLED,
        "domain":       ldap_auth._DOMAIN,
        "hosts":        ldap_auth._hosts(),
        "port":         ldap_auth._PORT,
        "use_ssl":      ldap_auth._USE_SSL,
        "starttls":     ldap_auth._STARTTLS,
        "base_dn":      ldap_auth._BASE_DN,
        "admin_group":  ldap_auth._ADMIN_GROUP,
    }

    if not ldap_auth.LDAP_ENABLED:
        return {"ok": False, "error": "LDAP not enabled (ldap3 not installed or LDAP_HOSTS not set)", "config": config_info}

    if not username or not password:
        return {"ok": False, "error": "username and password required", "config": config_info}

    ok, groups, error = ldap_auth.authenticate(username, password)
    permissions = portal_modules.resolve_permissions(groups) if ok else {}
    is_portal_admin = ok and portal_modules.portal_admin_group().lower() in {g.lower() for g in groups}
    is_domain_admin = ok and ldap_auth._ADMIN_GROUP.lower() in {g.lower() for g in groups}

    return {
        "ok":              ok,
        "error":           error,
        "groups":          groups,
        "permissions":     permissions,
        "is_portal_admin": is_portal_admin,
        "is_domain_admin": is_domain_admin,
        "config":          config_info,
    }


@app.get("/api/auth/me")
async def me(request: Request) -> Dict[str, Any]:
    sess = _get_session(request)
    if not sess:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": sess["user"],
        "is_admin": sess["is_admin"],
        "groups": sess.get("groups", []),
        "permissions": sess.get("permissions", {}),
    }


# --- Config ---

@app.get("/api/config")
async def get_config(request: Request) -> Dict[str, Any]:
    sess = _get_session(request)
    server_list = [{"ip": s["ip"], "name": s["name"], "os_type": s.get("os_type", "linux"),
                    "parent": s.get("parent"), "subnet": s.get("subnet"),
                    "web_url": s.get("web_url")} for s in SERVERS]
    portal_name = portal_modules._gs("portal_name", "Portal Cobaltax")
    return {
        "auth_enabled": AUTH_ENABLED,
        "auth_users": AUTH_USERS,
        "default_language": portal_modules._gs("default_language", DEFAULT_LANGUAGE),
        "refresh_interval": REFRESH_INTERVAL,
        "portal_name": portal_name,
        "authenticated": bool(sess),
        "user": sess["user"] if sess else None,
        "is_admin": sess["is_admin"] if sess else False,
        "permissions": sess.get("permissions", {}) if sess else {},
        "servers": server_list,
    }


# --- Modules ---

@app.get("/api/modules")
async def get_modules(request: Request) -> List[Dict[str, Any]]:
    sess = _require_session(request)
    perms = sess.get("permissions", {})
    result = []
    for m in portal_modules.BUILTIN_MODULES:
        if m["id"] in perms:
            result.append({**m, "permission": perms[m["id"]]})
    return result


# --- Settings (portal admin only) ---

@app.get("/api/settings")
async def get_settings(request: Request) -> Dict[str, Any]:
    _require_admin(request)
    return portal_modules.all_settings()


@app.put("/api/settings")
async def save_settings(request: Request) -> Dict[str, Any]:
    sess = _require_admin(request)
    data = await request.json()
    portal_modules.save_settings(data)
    log_event("settings_saved", {"user": sess["user"]})
    return {"ok": True}


# --- Servers ---

@app.get("/api/servers")
async def get_servers(request: Request) -> List[Dict[str, Any]]:
    _require_session(request)
    result = []
    for s in SERVERS:
        cached = _server_status.get(s["ip"], {
            "online": False, "ping": False, "ssh": False, "last_check": None, "resources": None
        })
        result.append({**s, **cached})
    return result


@app.get("/api/servers/stream")
async def status_stream(request: Request) -> StreamingResponse:
    _require_session(request)

    queue: asyncio.Queue = asyncio.Queue()
    _sse_subscribers.append(queue)

    snapshot = []
    for s in SERVERS:
        cached = _server_status.get(s["ip"], {
            "online": False, "ping": False, "ssh": False, "last_check": None, "resources": None
        })
        snapshot.append({**s, **cached})

    async def generate():
        try:
            yield f"data: {json.dumps({'type': 'snapshot', 'servers': snapshot}, default=str)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            try:
                _sse_subscribers.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ServerUpsertRequest(BaseModel):
    name: str
    ip: str
    os_type: str = "linux"
    ssh_user: str = ""
    ssh_password: str = ""
    ssh_port: int = 22
    ssh_key_path: str = ""
    parent: str = ""
    subnet: str = ""
    web_url: str = ""
    watts_idle: Optional[float] = None
    watts_max: Optional[float] = None


@app.post("/api/servers", status_code=201)
async def create_server(body: ServerUpsertRequest, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not sess["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
    if any(s["ip"] == body.ip for s in SERVERS):
        raise HTTPException(status_code=409, detail="A server with that IP already exists")
    entry = {k: v for k, v in body.model_dump().items() if v not in ("", None) or k in ("watts_idle", "watts_max")}
    entry["ssh_port"] = body.ssh_port
    entry["watts_idle"] = body.watts_idle
    entry["watts_max"] = body.watts_max
    import secure_config_store as _scs
    _scs.upsert_server(entry)
    _reload_servers_list()
    log_event("server_created", {"user": sess["user"], "ip": body.ip, "name": body.name})
    return entry


@app.put("/api/servers/{ip}")
async def update_server(ip: str, body: ServerUpsertRequest, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not sess["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
    idx = next((i for i, s in enumerate(SERVERS) if s["ip"] == ip), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Server not found")
    existing = SERVERS[idx]
    entry = {k: v for k, v in body.model_dump().items() if v not in ("", None) or k in ("watts_idle", "watts_max")}
    entry["ip"] = ip  # ensure IP is always from the path
    entry["ssh_port"] = body.ssh_port
    entry["watts_idle"] = body.watts_idle if body.watts_idle is not None else existing.get("watts_idle")
    entry["watts_max"] = body.watts_max if body.watts_max is not None else existing.get("watts_max")
    # Keep existing password if none provided
    if not body.ssh_password:
        entry.pop("ssh_password", None)
    import secure_config_store as _scs
    _scs.upsert_server({**existing, **entry})
    _reload_servers_list()
    log_event("server_updated", {"user": sess["user"], "ip": ip})
    return next((s for s in SERVERS if s["ip"] == ip), entry)


@app.delete("/api/servers/{ip}", status_code=204)
async def delete_server(ip: str, request: Request) -> None:
    sess = _require_session(request)
    if not sess["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
    import secure_config_store as _scs
    ok = _scs.delete_server(ip)
    if not ok:
        raise HTTPException(status_code=404, detail="Server not found or not in DB")
    _reload_servers_list()
    _server_status.pop(ip, None)
    log_event("server_deleted", {"user": sess["user"], "ip": ip})


@app.post("/api/servers/{ip}/refresh")
async def refresh_server(ip: str, request: Request) -> Dict[str, Any]:
    _require_session(request)
    server = next((s for s in SERVERS if s["ip"] == ip), None)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    def _check():
        status = _server_monitor.get_server_status(server)
        status.update({"ip": server["ip"], "name": server["name"],
                       "os_type": server.get("os_type", "linux"),
                       "parent": server.get("parent")})
        _server_status[ip] = status
        _broadcast({"type": "status", "server": status})

    threading.Thread(target=_check, daemon=True).start()
    return {"ok": True}


@app.post("/api/servers/{ip}/restart")
async def restart_server(ip: str, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    server = next((s for s in SERVERS if s["ip"] == ip), None)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    set_session_user(sess["user"])
    log_event("restart_initiated", {"server": server["name"], "ip": ip, "user": sess["user"]})

    def _do():
        ok, msg = _ssh_manager.restart_server(server)
        log_event("restart_executed", {"server": server["name"], "ip": ip, "success": ok, "msg": msg})
        _broadcast({"type": "action_result", "action": "restart", "ip": ip, "ok": ok, "message": msg})

    threading.Thread(target=_do, daemon=True).start()
    return {"ok": True, "message": "Restart initiated"}


@app.post("/api/servers/{ip}/test-ssh")
async def test_ssh(ip: str, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    server = next((s for s in SERVERS if s["ip"] == ip), None)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    set_session_user(sess["user"])

    def _do():
        client, err = _ssh_manager.create_ssh_client(server)
        if client:
            client.close()
            ok, msg = True, "SSH connection successful"
        else:
            ok, msg = False, err
        _broadcast({"type": "action_result", "action": "test-ssh", "ip": ip, "ok": ok, "message": msg})

    threading.Thread(target=_do, daemon=True).start()
    return {"ok": True}


@app.post("/api/servers/{ip}/test-sudo")
async def test_sudo(ip: str, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    server = next((s for s in SERVERS if s["ip"] == ip), None)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    set_session_user(sess["user"])

    def _do():
        ok, msg = _ssh_manager.test_sudo_access(server)
        _broadcast({"type": "action_result", "action": "test-sudo", "ip": ip, "ok": ok, "message": msg})

    threading.Thread(target=_do, daemon=True).start()
    return {"ok": True}


# --- Audit log (admin only) ---

@app.get("/api/audit")
async def get_audit(
    request: Request,
    limit: int = 500,
    event_filter: str = "",
    user_filter: str = "",
    text_filter: str = "",
) -> Dict[str, Any]:
    _require_admin(request)

    if not os.path.exists(AUDIT_LOG_PATH):
        return {"events": []}

    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if len(lines) > limit:
        lines = lines[-limit:]

    events = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        ev = obj.get("event", "")
        usr = str(obj.get("user", "") or "")
        details_str = json.dumps(obj.get("details") or {})
        if event_filter and event_filter.lower() not in ev.lower():
            continue
        if user_filter and user_filter.lower() not in usr.lower():
            continue
        if text_filter and text_filter.lower() not in details_str.lower():
            continue
        events.append(obj)
        if len(events) >= limit:
            break

    return {"events": events}


# --- Printers ---

_DEFAULT_PRINTERS: List[Dict[str, Any]] = []  # seed via scripts/seed_portal_config.py


def _load_printers() -> List[Dict[str, Any]]:
    try:
        raw = _secure_get_setting("printers_list")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return _DEFAULT_PRINTERS


def _save_printers(printers: List[Dict[str, Any]]) -> None:
    _secure_set_setting("printers_list", json.dumps(printers))


@app.get("/api/printers")
async def get_printers(request: Request) -> List[Dict[str, Any]]:
    _require_session(request)
    return _load_printers()


@app.get("/api/printers/ping")
async def ping_printers(request: Request) -> Dict[str, Any]:
    _require_session(request)
    printers = _load_printers()
    results: Dict[str, bool] = {}

    def _ping_one(ip: str) -> None:
        results[ip] = _server_monitor.ping_server(ip)

    threads = [threading.Thread(target=_ping_one, args=(p["ip"],), daemon=True) for p in printers]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=PING_TIMEOUT + 1)
    # Any IP that never wrote a result timed out → offline
    for p in printers:
        results.setdefault(p["ip"], False)
    return results


@app.put("/api/printers")
async def save_printers(request: Request) -> Dict[str, Any]:
    sess = _require_admin(request)
    printers = await request.json()
    if not isinstance(printers, list):
        raise HTTPException(status_code=400, detail="Expected a list")
    for p in printers:
        if not p.get("name") or not p.get("ip"):
            raise HTTPException(status_code=400, detail="Each printer needs name and ip")
    _save_printers(printers)
    log_event("printers_saved", {"user": sess["user"], "count": len(printers)})
    return {"ok": True}


@app.post("/api/printers/upload")
async def upload_installer(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    sess = _require_admin(request)
    # Sanitize filename — keep only safe characters
    safe = "".join(c for c in pathlib.Path(file.filename).name if c.isalnum() or c in "-_.")
    if not safe.lower().endswith(".exe"):
        raise HTTPException(status_code=400, detail="Only .exe files allowed")
    dest = _data_dir / "printers" / safe
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    dest.write_bytes(content)
    link = f"data/printers/{safe}"
    log_event("printer_installer_uploaded", {"user": sess["user"], "file": safe, "bytes": len(content)})
    return {"ok": True, "link": link, "filename": safe}


_OS_SLOTS = {
    "win11":    "Windows 11",
    "win10_64": "Windows 10 (64-bit)",
    "win10_32": "Windows 10 (32-bit)",
}


def _driver_dir(ip: str, os_slot: str) -> pathlib.Path:
    return _data_dir / "drivers" / ip.replace(".", "_") / os_slot


def _driver_inf(ip: str, os_slot: str) -> Optional[str]:
    """Return filename of the first .inf found for this printer/OS slot, or None."""
    d = _driver_dir(ip, os_slot)
    if d.exists():
        for f in d.iterdir():
            if f.suffix.lower() == ".inf":
                return f.name
    return None


def _generate_ps1(p: Dict[str, Any], base_url: str, os_slot: str = "win11") -> str:
    name         = p.get("name", "Printer")
    ip           = p.get("ip", "")
    location     = p.get("location", "")
    driver_name  = p.get("driver_name", "")
    port_name    = f"IP_{ip}"
    display_name = f"{name} - {location}" if location else name
    ip_slug      = ip.replace(".", "_")
    inf_file     = _driver_inf(ip, os_slot)
    os_label     = _OS_SLOTS.get(os_slot, os_slot)

    base_url = base_url.rstrip("/")

    if inf_file:
        driver_dir_url = f"{base_url}/data/drivers/{ip_slug}/{os_slot}"
        driver_block = f"""
# 2 — Install driver from CobaltaX portal ({os_label})
if (Get-PrinterDriver -Name $DriverName -ErrorAction SilentlyContinue) {{
    Write-Host "[OK] Driver already installed" -ForegroundColor Green
}} else {{
    Write-Host "Downloading driver from portal..."
    $tmp = "$env:TEMP\\cobaltax_driver_{ip_slug}_{os_slot}"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null

    foreach ($f in (Invoke-RestMethod "{driver_dir_url}/files.json")) {{
        Invoke-WebRequest "{driver_dir_url}/$f" -OutFile "$tmp\\$f"
    }}

    Write-Host "Installing driver with pnputil..."
    $result = & pnputil /add-driver "$tmp\\{inf_file}" /install
    if ($LASTEXITCODE -ne 0) {{
        Write-Warning "pnputil failed. Trying Add-PrinterDriver..."
        Add-PrinterDriver -Name $DriverName -ErrorAction Stop
    }}
    Write-Host "[OK] Driver installed" -ForegroundColor Green
}}"""
    else:
        driver_block = f"""
# 2 — Install driver from Windows Update ({os_label})
if (Get-PrinterDriver -Name $DriverName -ErrorAction SilentlyContinue) {{
    Write-Host "[OK] Driver already installed" -ForegroundColor Green
}} else {{
    Write-Host "Installing driver from Windows Update..."
    try {{
        Add-PrinterDriver -Name $DriverName -ErrorAction Stop
        Write-Host "[OK] Driver installed" -ForegroundColor Green
    }} catch {{
        Write-Warning "Automatic install failed."
        Write-Warning "Upload the {os_label} driver INF in the portal, then re-run this script."
        Read-Host "Press Enter to exit"; exit 1
    }}
}}"""

    return f"""#Requires -RunAsAdministrator
# CobaltaX Auto-Installer — {name} ({location})
# Generated by CobaltaX Portal — {base_url}
$ErrorActionPreference = 'Stop'
$PrinterName = "{display_name}"
$PortName    = "{port_name}"
$PrinterIP   = "{ip}"
$DriverName  = "{driver_name}"

Write-Host "=== CobaltaX Printer Installer ===" -ForegroundColor Cyan
Write-Host "Printer : $PrinterName"
Write-Host "IP      : $PrinterIP"
Write-Host ""

# 1 — TCP/IP port
if (Get-PrinterPort -Name $PortName -ErrorAction SilentlyContinue) {{
    Write-Host "[OK] Port $PortName already exists" -ForegroundColor Green
}} else {{
    Write-Host "Creating port $PortName..."
    Add-PrinterPort -Name $PortName -PrinterHostAddress $PrinterIP
    Write-Host "[OK] Port created" -ForegroundColor Green
}}
{driver_block}

# 3 — Add printer
if (Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue) {{
    Write-Host "Updating existing printer port..."
    Set-Printer -Name $PrinterName -PortName $PortName
}} else {{
    Write-Host "Adding printer '$PrinterName'..."
    Add-Printer -Name $PrinterName -DriverName $DriverName -PortName $PortName
}}

Write-Host ""
Write-Host "[DONE] '$PrinterName' is ready to use." -ForegroundColor Green
Read-Host "Press Enter to close"
"""


@app.post("/api/printers/{ip}/driver")
async def upload_driver_files(
    ip: str, request: Request,
    files: List[UploadFile] = File(...),
    os_slot: str = Query("win11"),
) -> Dict[str, Any]:
    sess = _require_admin(request)
    if os_slot not in _OS_SLOTS:
        raise HTTPException(status_code=400, detail=f"Invalid os_slot. Choose from: {list(_OS_SLOTS)}")
    d = _driver_dir(ip, os_slot)
    d.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        safe = "".join(c for c in pathlib.Path(f.filename).name if c.isalnum() or c in "-_.")
        (d / safe).write_bytes(await f.read())
        saved.append(safe)
    (d / "files.json").write_text(json.dumps(saved))
    log_event("driver_uploaded", {"user": sess["user"], "ip": ip, "os_slot": os_slot, "files": saved})
    return {"ok": True, "os_slot": os_slot, "files": saved}


@app.get("/api/printers/{ip}/driver/status")
async def driver_status(ip: str, request: Request) -> Dict[str, Any]:
    _require_session(request)
    slots = {}
    for slot in _OS_SLOTS:
        inf = _driver_inf(ip, slot)
        d = _driver_dir(ip, slot)
        files = [f.name for f in d.iterdir() if f.name != "files.json"] if d.exists() else []
        slots[slot] = {"label": _OS_SLOTS[slot], "has_driver": inf is not None, "inf": inf, "files": files}
    return {"slots": slots}


@app.get("/api/printers/{ip}/install.ps1")
async def download_install_script(ip: str, request: Request, os_slot: str = Query("win11")):
    _require_session(request)
    if os_slot not in _OS_SLOTS:
        raise HTTPException(status_code=400, detail=f"Invalid os_slot. Choose from: {list(_OS_SLOTS)}")
    printers = _load_printers()
    p = next((x for x in printers if x["ip"] == ip), None)
    if not p:
        raise HTTPException(status_code=404, detail="Printer not found")
    base_url = str(request.base_url).rstrip("/")
    script = _generate_ps1(p, base_url, os_slot)
    safe_name = ''.join(c if c.isalnum() else '_' for c in p.get('name', 'printer'))
    os_label = _OS_SLOTS[os_slot].replace(" ", "_").replace("(", "").replace(")", "").replace("-", "")
    filename = f"Install_{safe_name}_{os_label}.ps1"
    return Response(
        content=script.encode("utf-8-sig"),  # BOM so Windows opens correctly
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Monitored Applications ---

def _load_apps() -> List[Dict[str, Any]]:
    try:
        raw = _secure_get_setting("monitored_apps")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return []


def _http_check(app: Dict[str, Any]) -> Dict[str, Any]:
    import requests as _req
    try:
        r = _req.get(app["url"], timeout=5, allow_redirects=True)
        return {**app, "online": r.status_code < 500, "status_code": r.status_code, "checked_at": time.time()}
    except Exception as exc:
        return {**app, "online": False, "error": str(exc)[:120], "checked_at": time.time()}


@app.get("/api/apps/monitor")
async def monitor_apps(request: Request) -> List[Dict[str, Any]]:
    _require_session(request)
    apps = _load_apps()
    loop = asyncio.get_event_loop()
    results = await asyncio.gather(*[
        loop.run_in_executor(None, _http_check, a) for a in apps
    ])
    return list(results)


# --- Backup monitoring ---

def _load_backups() -> List[Dict[str, Any]]:
    try:
        raw = _secure_get_setting("backup_jobs")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return []


@app.get("/api/backups")
async def get_backups(request: Request) -> List[Dict[str, Any]]:
    _require_session(request)
    return _load_backups()


@app.post("/api/backups/restore")
async def request_restore(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    body = await request.json()
    backup_id = body.get("backup_id", "")
    note = body.get("note", "")
    log_event("restore_requested", {"backup_id": backup_id, "note": note}, user=sess.get("user"))
    return {"ok": True, "message": "Restore request submitted. The IT team will contact you shortly."}


# --- Energy module ---

@app.get("/api/energy")
async def get_energy(request: Request) -> Dict[str, Any]:
    _require_session(request)
    now   = time.time()
    price = _get_energy_price()
    rows  = []
    for server in SERVERS:
        summary = _energy_summary(server["ip"], now)
        rows.append({
            "ip":      server["ip"],
            "name":    server["name"],
            "os_type": server.get("os_type", "linux"),
            "parent":  server.get("parent"),
            "is_vm":   bool(server.get("parent") and server.get("watts_max", 1) == 0),
            "current_watts": summary["current_watts"],
            "periods": {
                label: {
                    "kwh":      d['kwh'],
                    "cost":     round(d['kwh'] * price, 4),
                    "coverage": d['coverage'],
                }
                for label, d in summary["periods"].items()
            },
        })
    # Fleet totals — coverage is the min across all servers for that period
    totals: Dict[str, Any] = {}
    for label in ("1h", "24h", "7d", "30d"):
        kwh      = sum(r["periods"][label]["kwh"] for r in rows)
        coverage = min((r["periods"][label]["coverage"] for r in rows), default=0.0)
        totals[label] = {"kwh": round(kwh, 3), "cost": round(kwh * price, 3), "coverage": round(coverage, 3)}
    # Projected monthly based on current wattage of physical servers (not VMs)
    current_watts_total = sum(
        (r["current_watts"] or 0) for r in rows
        if not any(s["ip"] == r["ip"] and s.get("watts_max", 1) == 0 and s.get("parent")
                   for s in SERVERS)
    )
    projected_monthly_kwh  = round(current_watts_total * 24 * 30 / 1000, 1)
    projected_monthly_cost = round(projected_monthly_kwh * price, 2)
    totals["projected_month"] = {"kwh": projected_monthly_kwh, "cost": projected_monthly_cost,
                                  "watts": round(current_watts_total, 1)}
    return {"servers": rows, "totals": totals, "price_kwh": price, "currency": "€"}


@app.get("/api/energy/settings")
async def get_energy_settings(request: Request) -> Dict[str, Any]:
    _require_admin(request)
    return {
        "price_kwh": _get_energy_price(),
        "profiles":  _ENERGY_WATTAGE,
    }


@app.post("/api/energy/settings")
async def save_energy_settings(request: Request) -> Dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    if "price_kwh" in body:
        try:
            price = float(body["price_kwh"])
            if _secure_set_setting:
                _secure_set_setting("energy_price_kwh", str(price))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid price value")
    return {"ok": True}


# --- Translations ---

_TRANSLATIONS: Dict[str, Dict[str, str]] = {}
_TRANSLATIONS_DIR = pathlib.Path(__file__).parent / "translations"


@app.get("/api/translations/{lang}")
async def get_translations(lang: str) -> Dict[str, str]:
    if lang not in ("en", "es", "ca"):
        lang = "en"
    if lang not in _TRANSLATIONS:
        path = _TRANSLATIONS_DIR / f"{lang}.json"
        _TRANSLATIONS[lang] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _TRANSLATIONS[lang]


# --- SSH Terminal (WebSocket) ---

@app.websocket("/ws/ssh/{ip}")
async def ssh_terminal(websocket: WebSocket, ip: str, rows: int = 24, cols: int = 80) -> None:
    token = websocket.cookies.get(_SESSION_COOKIE)
    sess = _sessions.get(token)
    if not sess or time.time() - sess["ts"] > _SESSION_TTL:
        await websocket.close(code=4401)
        return
    if sess.get("permissions", {}).get("health") != "admin":
        await websocket.close(code=4403)
        return
    server = next((s for s in SERVERS if s["ip"] == ip), None)
    if not server:
        await websocket.close(code=4404)
        return

    await websocket.accept()

    client, err = _ssh_manager.create_ssh_client(server)
    if not client:
        await websocket.send_text(json.dumps({"type": "data", "data": f"\r\n\x1b[31mSSH failed: {err}\x1b[0m\r\n"}))
        await websocket.close()
        return

    log_event("ssh_terminal_opened", {"user": sess["user"], "server": server["name"], "ip": ip})
    channel = client.invoke_shell(term="xterm-256color", width=cols, height=rows)
    loop = asyncio.get_event_loop()

    async def _read() -> None:
        try:
            while True:
                ready = await loop.run_in_executor(
                    None, lambda: select.select([channel], [], [], 0.2)[0]
                )
                if ready:
                    data = channel.recv(4096)
                    if not data:
                        break
                    await websocket.send_text(json.dumps({
                        "type": "data",
                        "data": data.decode("utf-8", errors="replace"),
                    }))
                if channel.exit_status_ready() and not channel.recv_ready():
                    break
        except Exception:
            pass

    async def _write() -> None:
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    msg = json.loads(raw)
                    if msg.get("type") == "resize":
                        channel.resize_pty(width=int(msg["cols"]), height=int(msg["rows"]))
                    elif msg.get("type") == "data":
                        channel.send(msg["data"].encode("utf-8", errors="replace"))
                except asyncio.TimeoutError:
                    pass
                except WebSocketDisconnect:
                    break
        except Exception:
            pass

    read_task  = asyncio.create_task(_read())
    write_task = asyncio.create_task(_write())
    try:
        await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        read_task.cancel()
        write_task.cancel()
        log_event("ssh_terminal_closed", {"user": sess["user"], "server": server["name"], "ip": ip})
        channel.close()
        client.close()


# --- Apps module ---

_BUILTIN_APPS: List[Dict[str, Any]] = [
    {
        "id": "chrome",
        "label": "Google Chrome",
        "icon": "🌐",
        "description": "Web browser by Google",
        "url": "https://dl.google.com/chrome/install/ChromeSetup.exe",
        "url_type": "external",   # opens/downloads from external URL
    },
    {
        "id": "whatsapp",
        "label": "WhatsApp",
        "icon": "💬",
        "description": "WhatsApp Desktop",
        "url": "https://www.whatsapp.com/download",
        "url_type": "external",
    },
    {
        "id": "office2017",
        "label": "Microsoft Office 2017",
        "icon": "📄",
        "description": "Microsoft Office 2017 — silent installer",
        "url": None,
        "url_type": "upload",     # admin must upload; served locally
    },
    {
        "id": "wireguard",
        "label": "WireGuard",
        "icon": "🔒",
        "description": "WireGuard VPN client",
        "url": "https://www.wireguard.com/install/",
        "url_type": "external",
    },
]

_apps_dir = _data_dir / "apps"
_apps_dir.mkdir(exist_ok=True)


def _app_upload_url(app_id: str) -> Optional[str]:
    d = _apps_dir / app_id
    if d.exists():
        for f in d.iterdir():
            if f.suffix.lower() in (".exe", ".msi"):
                return f"data/apps/{app_id}/{f.name}"
    return None


def _load_app_links() -> List[Dict[str, Any]]:
    try:
        raw = _secure_get_setting("apps_links")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return []


def _save_app_links(links: List[Dict[str, Any]]) -> None:
    _secure_set_setting("apps_links", json.dumps(links))


@app.get("/api/apps")
async def get_apps(request: Request) -> Dict[str, Any]:
    _require_session(request)
    apps = []
    for a in _BUILTIN_APPS:
        entry = dict(a)
        if a["url_type"] == "upload":
            uploaded = _app_upload_url(a["id"])
            entry["url"] = uploaded
            entry["uploaded"] = bool(uploaded)
        apps.append(entry)
    return {"apps": apps, "links": _load_app_links()}


@app.put("/api/apps/links")
async def save_app_links(request: Request) -> Dict[str, Any]:
    sess = _require_admin(request)
    links = await request.json()
    if not isinstance(links, list):
        raise HTTPException(status_code=400, detail="Expected a list")
    for lnk in links:
        if not lnk.get("label") or not lnk.get("url"):
            raise HTTPException(status_code=400, detail="Each link needs label and url")
    _save_app_links(links)
    log_event("app_links_saved", {"user": sess["user"], "count": len(links)})
    return {"ok": True}


@app.post("/api/apps/{app_id}/upload")
async def upload_app_installer(
    app_id: str, request: Request, file: UploadFile = File(...)
) -> Dict[str, Any]:
    sess = _require_admin(request)
    known = {a["id"] for a in _BUILTIN_APPS if a["url_type"] == "upload"}
    if app_id not in known:
        raise HTTPException(status_code=400, detail=f"Unknown upload slot '{app_id}'")
    safe = "".join(c for c in pathlib.Path(file.filename).name if c.isalnum() or c in "-_.")
    if not safe.lower().endswith((".exe", ".msi")):
        raise HTTPException(status_code=400, detail="Only .exe or .msi files allowed")
    dest_dir = _apps_dir / app_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.iterdir():
        old.unlink()
    content = await file.read()
    (dest_dir / safe).write_bytes(content)
    url = f"data/apps/{app_id}/{safe}"
    log_event("app_installer_uploaded", {"user": sess["user"], "app": app_id, "file": safe, "bytes": len(content)})
    return {"ok": True, "url": url, "filename": safe}


# --- Support module ---

_SUPPORT_CATEGORIES = ["general", "hardware", "software", "network", "access", "other"]
_SUPPORT_PRIORITIES = ["low", "medium", "high", "urgent"]
_SUPPORT_STATUSES   = ["open", "in_progress", "resolved", "closed"]


@app.get("/api/support/tickets")
async def support_list_tickets(
    request: Request,
    status: str = "", category: str = "", priority: str = "",
) -> List[Dict[str, Any]]:
    sess = _require_session(request)
    return support_db.list_tickets(
        sess["user"], sess["is_admin"],
        status=status, category=category, priority=priority,
    )


@app.post("/api/support/tickets")
async def support_create_ticket(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    body = await request.json()
    title    = (body.get("title") or "").strip()
    desc     = (body.get("description") or "").strip()
    category = body.get("category", "general")
    priority = body.get("priority", "medium")
    if not title or not desc:
        raise HTTPException(status_code=400, detail="title and description required")
    if category not in _SUPPORT_CATEGORIES:
        category = "general"
    if priority not in _SUPPORT_PRIORITIES:
        priority = "medium"
    tid = support_db.create_ticket(title, desc, category, priority, sess["user"])
    log_event("ticket_created", {"user": sess["user"], "ticket_id": tid, "title": title})
    return {"ok": True, "id": tid}


@app.get("/api/support/tickets/{tid}")
async def support_get_ticket(tid: int, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    ticket = support_db.get_ticket(tid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not sess["is_admin"] and ticket["created_by"] != sess["user"]:
        raise HTTPException(status_code=403, detail="Access denied")
    comments    = support_db.list_comments(tid)
    attachments = support_db.list_attachments(tid)
    return {"ticket": ticket, "comments": comments, "attachments": attachments}


@app.put("/api/support/tickets/{tid}")
async def support_update_ticket(tid: int, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    ticket = support_db.get_ticket(tid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    body = await request.json()
    # Users can only update title/description if still open
    if sess["is_admin"]:
        allowed_fields = {"title", "description", "category", "priority", "status", "assigned_to"}
    else:
        if ticket["created_by"] != sess["user"]:
            raise HTTPException(status_code=403, detail="Access denied")
        if ticket["status"] not in ("open",):
            raise HTTPException(status_code=400, detail="Cannot edit a ticket that is not open")
        allowed_fields = {"title", "description"}
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    support_db.update_ticket(tid, **updates)
    log_event("ticket_updated", {"user": sess["user"], "ticket_id": tid, "fields": list(updates)})
    return {"ok": True}


@app.post("/api/support/tickets/{tid}/comments")
async def support_add_comment(tid: int, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    ticket = support_db.get_ticket(tid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not sess["is_admin"] and ticket["created_by"] != sess["user"]:
        raise HTTPException(status_code=403, detail="Access denied")
    body = await request.json()
    text = (body.get("body") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="comment body required")
    cid = support_db.add_comment(tid, sess["user"], text)
    return {"ok": True, "id": cid}


@app.post("/api/support/tickets/{tid}/attachments")
async def support_upload_attachment(
    tid: int, request: Request,
    files: List[UploadFile] = File(...),
    comment_id: Optional[int] = Query(None),
) -> Dict[str, Any]:
    sess = _require_session(request)
    ticket = support_db.get_ticket(tid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not sess["is_admin"] and ticket["created_by"] != sess["user"]:
        raise HTTPException(status_code=403, detail="Access denied")
    saved = []
    for f in files:
        data = await f.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"{f.filename} exceeds 20 MB limit")
        aid = support_db.save_attachment(tid, comment_id, f.filename, data, sess["user"])
        saved.append({"id": aid, "filename": f.filename})
    return {"ok": True, "attachments": saved}


@app.get("/api/support/attachments/{aid}")
async def support_download_attachment(aid: int, request: Request):
    sess = _require_session(request)
    att = support_db.get_attachment(aid)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    ticket = support_db.get_ticket(att["ticket_id"])
    if not ticket:
        raise HTTPException(status_code=404)
    if not sess["is_admin"] and ticket["created_by"] != sess["user"]:
        raise HTTPException(status_code=403, detail="Access denied")
    data = support_db.get_attachment_bytes(aid)
    if data is None:
        raise HTTPException(status_code=404, detail="File data not found")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{att["filename"]}"'},
    )


@app.get("/api/support/meta")
async def support_meta(request: Request) -> Dict[str, Any]:
    _require_session(request)
    return {
        "categories": _SUPPORT_CATEGORIES,
        "priorities":  _SUPPORT_PRIORITIES,
        "statuses":    _SUPPORT_STATUSES,
        "users":       AUTH_USERS,
    }


@app.get("/api/support/stats")
async def support_stats(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    return support_db.get_stats(sess["user"], sess["is_admin"])


@app.post("/api/support/ai_assist")
async def support_ai_assist(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    body = await request.json()
    ticket_ctx = body.get("ticket_context", "")
    question   = body.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question required")

    import anthropic as _ant
    client = _ant.Anthropic()
    system = (
        "You are a helpful IT support assistant for Cobaltax. "
        "You help support technicians handle tickets efficiently. "
        "Be concise, professional, and practical. "
        "Answer in the same language as the question (Spanish or English).\n\n"
        f"TICKET CONTEXT:\n{ticket_ctx}"
    )
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": question}],
    )
    answer = msg.content[0].text if msg.content else ""
    return {"answer": answer}


# --- VPN module ---

@app.get("/api/vpn/configs")
async def vpn_list_configs(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    configs = support_db.list_vpn_configs(sess["user"], sess["is_admin"])
    return {"configs": configs}


@app.post("/api/vpn/configs")
async def vpn_upload_config(
    request: Request,
    name: str = Form(...),
    assigned_to: str = Form(...),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    sess = _require_admin(request)
    if not file.filename.endswith(".conf"):
        raise HTTPException(status_code=400, detail="Only .conf files allowed")
    safe = "".join(c for c in pathlib.Path(file.filename).name if c.isalnum() or c in "-_.")
    if not safe:
        safe = "config.conf"
    data = await file.read()
    cid = support_db.upload_vpn_config(name.strip(), safe, assigned_to.strip(), data, sess["user"])
    log_event("vpn_config_uploaded", {"user": sess["user"], "assigned_to": assigned_to, "name": name})
    return {"ok": True, "id": cid}


@app.get("/api/vpn/configs/{cid}/download")
async def vpn_download_config(cid: int, request: Request):
    sess = _require_session(request)
    cfg = support_db.get_vpn_config(cid)
    if not cfg:
        raise HTTPException(status_code=404, detail="Config not found")
    if not sess["is_admin"] and cfg["assigned_to"] != sess["user"]:
        raise HTTPException(status_code=403, detail="Access denied")
    data = support_db.get_vpn_config_bytes(cid)
    if data is None:
        raise HTTPException(status_code=404, detail="File data not found")
    log_event("vpn_config_downloaded", {"user": sess["user"], "config_id": cid, "name": cfg["name"]})
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{cfg["filename"]}"'},
    )


@app.delete("/api/vpn/configs/{cid}")
async def vpn_delete_config(cid: int, request: Request) -> Dict[str, Any]:
    sess = _require_admin(request)
    cfg = support_db.get_vpn_config(cid)
    if not cfg:
        raise HTTPException(status_code=404, detail="Config not found")
    support_db.delete_vpn_config(cid)
    log_event("vpn_config_deleted", {"user": sess["user"], "config_id": cid, "name": cfg["name"]})
    return {"ok": True}


# ── Workstation Centers API ────────────────────────────────

@app.get("/api/workstations/centers")
async def ws_list_centers(request: Request) -> List[Dict[str, Any]]:
    _require_session(request)
    return support_db.list_centers()


@app.post("/api/workstations/centers")
async def ws_create_center(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not sess["is_admin"]:
        raise HTTPException(403, "Admin only")
    body = await request.json()
    cid = support_db.create_center(body.get("name", "").strip(), body.get("location", "").strip())
    return {"id": cid}


@app.put("/api/workstations/centers/{cid}")
async def ws_update_center(cid: int, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not sess["is_admin"]:
        raise HTTPException(403, "Admin only")
    body = await request.json()
    support_db.update_center(cid, body.get("name", "").strip(), body.get("location", "").strip())
    return {"ok": True}


@app.delete("/api/workstations/centers/{cid}")
async def ws_delete_center(cid: int, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not sess["is_admin"]:
        raise HTTPException(403, "Admin only")
    support_db.delete_center(cid)
    return {"ok": True}


@app.get("/api/workstations")
async def ws_list(request: Request, center_id: Optional[int] = None) -> List[Dict[str, Any]]:
    _require_session(request)
    return support_db.list_workstations(center_id)


@app.post("/api/workstations")
async def ws_create(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not sess["is_admin"]:
        raise HTTPException(403, "Admin only")
    b = await request.json()
    wid = support_db.create_workstation(
        int(b["center_id"]), b.get("name", "").strip(), b.get("ip", "").strip(),
        b.get("os_type", "windows"), b.get("assigned_user", "").strip(),
        b.get("ram_gb") or None, b.get("cpu_model", "").strip() or None,
        b.get("disk_gb") or None, b.get("notes", "").strip() or None,
    )
    return {"id": wid}


@app.put("/api/workstations/{wid}")
async def ws_update(wid: int, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not sess["is_admin"]:
        raise HTTPException(403, "Admin only")
    b = await request.json()
    fields = {k: b.get(k) for k in ('center_id', 'name', 'ip', 'os_type', 'assigned_user', 'ram_gb', 'cpu_model', 'disk_gb', 'notes')}
    support_db.update_workstation(wid, **{k: v for k, v in fields.items() if v is not None or k in ('ip', 'notes', 'assigned_user')})
    return {"ok": True}


@app.delete("/api/workstations/{wid}")
async def ws_delete(wid: int, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not sess["is_admin"]:
        raise HTTPException(403, "Admin only")
    support_db.delete_workstation(wid)
    return {"ok": True}


@app.post("/api/workstations/ping")
async def ws_ping_batch(request: Request) -> Dict[str, Any]:
    """Ping a list of IPs and return {ip: bool} results."""
    import sys
    _require_session(request)
    body = await request.json()
    ips = [str(x) for x in (body.get("ips") or []) if x][:50]  # max 50
    results: Dict[str, Any] = {}

    async def _ping(ip: str) -> bool:
        try:
            if sys.platform == "win32":
                cmd = ["ping", "-n", "1", "-w", "1000", ip]
            elif sys.platform == "darwin":
                cmd = ["ping", "-c", "1", "-W", "1000", ip]
            else:
                cmd = ["ping", "-c", "1", "-W", "1", ip]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=3)
            return proc.returncode == 0
        except Exception:
            return False

    tasks = {ip: asyncio.ensure_future(_ping(ip)) for ip in ips}
    await asyncio.gather(*tasks.values(), return_exceptions=True)
    for ip, task in tasks.items():
        results[ip] = task.result() if not task.exception() else False
    return results


# --- Wiki module ---

@app.get("/api/wiki/categories")
async def wiki_list_categories(request: Request) -> Dict[str, Any]:
    _require_session(request)
    return {"categories": wiki_db.list_categories()}


@app.post("/api/wiki/categories")
async def wiki_create_category(request: Request) -> Dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    cat = wiki_db.create_category(name, body.get("description", ""))
    return {"category": cat}


@app.put("/api/wiki/categories/{slug}")
async def wiki_update_category(slug: str, request: Request) -> Dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    cat = wiki_db.save_category(
        slug,
        str(body.get("name", slug)).strip(),
        body.get("description", ""),
        int(body.get("order", 99)),
    )
    return {"category": cat}


@app.delete("/api/wiki/categories/{slug}")
async def wiki_delete_category(slug: str, request: Request) -> Dict[str, Any]:
    _require_admin(request)
    if not wiki_db.delete_category(slug):
        raise HTTPException(status_code=404, detail="Category not found")
    return {"ok": True}


@app.get("/api/wiki/categories/{cat_slug}/articles")
async def wiki_list_articles(cat_slug: str, request: Request) -> Dict[str, Any]:
    _require_session(request)
    return {"articles": wiki_db.list_articles(cat_slug)}


@app.get("/api/wiki/articles/{cat_slug}/{art_slug}")
async def wiki_get_article(cat_slug: str, art_slug: str, request: Request) -> Dict[str, Any]:
    _require_session(request)
    art = wiki_db.get_article(cat_slug, art_slug)
    if not art:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"article": art}


@app.post("/api/wiki/articles/{cat_slug}")
async def wiki_create_article(cat_slug: str, request: Request) -> Dict[str, Any]:
    sess = _require_admin(request)
    if not wiki_db.get_category(cat_slug):
        raise HTTPException(status_code=404, detail="Category not found")
    body = await request.json()
    title = str(body.get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    art = wiki_db.create_article(
        cat_slug, title,
        body.get("content", ""),
        sess["user"],
        body.get("tags", []),
    )
    log_event("wiki_article_created", {"user": sess["user"], "cat": cat_slug, "title": title})
    return {"article": art}


@app.put("/api/wiki/articles/{cat_slug}/{art_slug}")
async def wiki_update_article(cat_slug: str, art_slug: str, request: Request) -> Dict[str, Any]:
    sess = _require_admin(request)
    body = await request.json()
    title = str(body.get("title", art_slug)).strip()
    art = wiki_db.update_article(
        cat_slug, art_slug, title,
        body.get("content", ""),
        sess["user"],
        body.get("tags", []),
    )
    if not art:
        raise HTTPException(status_code=404, detail="Article not found")
    log_event("wiki_article_updated", {"user": sess["user"], "cat": cat_slug, "slug": art_slug})
    return {"article": art}


@app.delete("/api/wiki/articles/{cat_slug}/{art_slug}")
async def wiki_delete_article(cat_slug: str, art_slug: str, request: Request) -> Dict[str, Any]:
    sess = _require_admin(request)
    if not wiki_db.delete_article(cat_slug, art_slug):
        raise HTTPException(status_code=404, detail="Article not found")
    log_event("wiki_article_deleted", {"user": sess["user"], "cat": cat_slug, "slug": art_slug})
    return {"ok": True}


@app.get("/api/wiki/search")
async def wiki_search(q: str, request: Request) -> Dict[str, Any]:
    _require_session(request)
    if not q or len(q) < 2:
        return {"results": []}
    return {"results": wiki_db.search_articles(q)}


@app.get("/api/wiki/export")
async def wiki_export(request: Request) -> Dict[str, Any]:
    """Flat export of all articles — intended for LLM ingestion."""
    _require_session(request)
    return {"articles": wiki_db.export_all()}


# --- AI Assistant ---

try:
    import anthropic as _anthropic
    _anthropic_client = _anthropic.Anthropic(
        api_key=os.environ.get("AI_API_KEY") or (_secure_get_setting("AI_API_KEY") if callable(_secure_get_setting) else None)
    )
    _AI_AVAILABLE = True
except Exception:
    _anthropic_client = None
    _AI_AVAILABLE = False

_AI_TOOLS = [
    {
        "name": "get_servers_status",
        "description": "Get the current live status of all monitored servers and network devices (ping, SSH, resources).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_printers_status",
        "description": "Get the list of printers and their current ping reachability.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "ping_device",
        "description": "Ping any IP address on the network to check if it is reachable.",
        "input_schema": {
            "type": "object",
            "properties": {"ip": {"type": "string", "description": "IP address to ping"}},
            "required": ["ip"],
        },
    },
    {
        "name": "restart_server",
        "description": "Restart a server by IP. Admin only. Always tell the user what you are about to do before calling this.",
        "input_schema": {
            "type": "object",
            "properties": {"ip": {"type": "string", "description": "IP address of the server to restart"}},
            "required": ["ip"],
        },
    },
    {
        "name": "get_printer_install_link",
        "description": "Get the PowerShell installer download URL for a printer. Return it to the user with instructions to run it as Administrator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "Printer IP address"},
                "os_slot": {"type": "string", "enum": ["win11", "win10_64", "win10_32"], "description": "Target Windows version"},
            },
            "required": ["ip", "os_slot"],
        },
    },
    {
        "name": "search_wiki",
        "description": "Search the Cobaltax IT wiki for procedures, runbooks, and documentation.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search terms"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_wiki_article",
        "description": "Fetch the full content of a specific wiki article.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cat_slug": {"type": "string", "description": "Category slug"},
                "art_slug": {"type": "string", "description": "Article slug"},
            },
            "required": ["cat_slug", "art_slug"],
        },
    },
    {
        "name": "create_wiki_category",
        "description": "Create a new wiki category for organising IT documentation. Check existing categories first to avoid duplicates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Category name, e.g. 'Network', 'Servers', 'Procedures'"},
                "description": {"type": "string", "description": "Short description of what belongs in this category"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_wiki_article",
        "description": "Create a new wiki article to document IT infrastructure information gathered during the interview.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cat_slug": {"type": "string", "description": "Slug of the category (must exist — create it first if needed)"},
                "title": {"type": "string", "description": "Article title"},
                "content": {"type": "string", "description": "Article content in Markdown — be specific: include IPs, ports, paths, versions"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for searchability"},
            },
            "required": ["cat_slug", "title", "content", "tags"],
        },
    },
    {
        "name": "update_wiki_article",
        "description": "Update an existing wiki article with new or corrected information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cat_slug": {"type": "string", "description": "Category slug"},
                "art_slug": {"type": "string", "description": "Article slug"},
                "title": {"type": "string", "description": "Article title (unchanged if not edited)"},
                "content": {"type": "string", "description": "Full updated article content in Markdown"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Updated tags"},
            },
            "required": ["cat_slug", "art_slug", "title", "content", "tags"],
        },
    },
]


def _build_system_prompt(sess: Dict[str, Any]) -> str:
    is_admin = sess.get("is_admin", False)
    user = sess.get("user", "unknown")

    server_lines = []
    for s in SERVERS:
        cached = _server_status.get(s["ip"], {})
        status = "🟢 Online" if cached.get("online") else "🔴 Offline"
        server_lines.append(
            f"- {s['name']} ({s['ip']}) [{s.get('os_type', 'linux')}] {s.get('subnet', '')} — {status}"
        )

    printer_lines = [
        f"- {p['name']} · {p.get('location', '?')} · {p['ip']} [{p.get('subnet', '?')}]"
        for p in _load_printers()
    ]

    return f"""You are the IT assistant for Cobaltax, a company in Spain. You help staff manage and troubleshoot their IT infrastructure.

## User
- Name: {user}
- Role: {'Administrator — can restart servers and take all actions' if is_admin else 'Standard user — read-only, cannot restart servers'}

## Network
{_secure_get_setting("NETWORK_DESCRIPTION") or "(not configured — set NETWORK_DESCRIPTION in Settings)"}

## Servers
{chr(10).join(server_lines)}

## Printers
{chr(10).join(printer_lines)}

## Guidelines
- Be concise and practical. Use bullet points for steps.
- Use tools to get live data before answering status questions.
- For server restarts, always describe the action to the user first, then call the tool.
- For printer installs, use get_printer_install_link and tell the user to run the PS1 as Administrator.
- Reply in the same language the user writes in (Spanish, Catalan, or English).
- If the user asks about something not in context, search the wiki first."""


def _build_wiki_interview_prompt(sess: Dict[str, Any]) -> str:
    user = sess.get("user", "unknown")
    cats = wiki_db.list_categories()
    existing_cats = (
        "\n".join(f"- {c['name']} (slug: {c['slug']}): {c.get('description', '')}" for c in cats)
        if cats else "None yet — you will need to create them."
    )
    return f"""You are a structured IT documentation interviewer for Cobaltax. Your job is to interview {user} and build a complete IT wiki by asking questions and immediately documenting the answers.

## How you work
1. Ask ONE clear question at a time — never ask multiple questions at once
2. After the user answers, immediately call create_wiki_article or update_wiki_article to document what you learned, then confirm to the user what you saved
3. Ask the next question only after documenting the previous answer
4. If the user skips or doesn't know, note it and move on
5. Reply in the same language the user writes in (Spanish, Catalan, or English)
6. Keep questions conversational and short

## Existing wiki categories
{existing_cats}

## Interview topics — work through these in order
1. **Network overview** — subnets, VLANs, ISP, external IPs/DNS, Wi-Fi SSIDs, bandwidth
2. **Servers** — for each: purpose, OS version, specs, physical location, criticality
3. **Services** — what apps/services run on each server (web, DB, AD, DNS, DHCP, file share…)
4. **Backups** — what gets backed up, where, how often, who is responsible, recovery steps
5. **Key contacts** — IT vendor, ISP support line, hardware support, internal responsible people
6. **Maintenance** — update policy, scheduled tasks, reboot windows
7. **Security** — password policy, VPN access, firewall rules, who has admin rights
8. **Common issues & runbooks** — known problems and their solutions
9. **Software & licences** — key software, licence key locations, renewal dates
10. **Hardware inventory** — switches, APs, NAS, UPS, printers — model, location, IP

## Wiki article rules
- Use Markdown with clear headings (## subheadings are enough)
- Be specific: include IPs, ports, paths, version numbers when the user provides them
- Each article covers ONE clear topic
- Preferred category slugs: network, servers, services, backups, contacts, procedures, security, runbooks, software, hardware
- Always check if a category already exists before creating a new one; create it if missing

Start by greeting {user} warmly, explaining in 2-3 sentences what this mode does and roughly how long it takes, then dive straight into the first question."""


async def _execute_ai_tool(name: str, inp: Dict, sess: Dict) -> str:
    if name == "get_servers_status":
        lines = []
        for s in SERVERS:
            c = _server_status.get(s["ip"], {})
            res = c.get("resources") or {}
            extra = []
            if res.get("cpu_percent") is not None:
                extra.append(f"CPU {res['cpu_percent']}%")
            if res.get("mem_percent") is not None:
                extra.append(f"RAM {res['mem_percent']}%")
            status = "🟢 Online" if c.get("online") else "🔴 Offline"
            lines.append(f"- {s['name']} ({s['ip']}): {status}" + (f" — {', '.join(extra)}" if extra else ""))
        return "\n".join(lines) or "No server data available."

    if name == "get_printers_status":
        printers = _load_printers()
        results = {}
        def _p(pr): results[pr["ip"]] = _server_monitor.ping_server(pr["ip"])
        threads = [threading.Thread(target=_p, args=(pr,), daemon=True) for pr in printers]
        for th in threads: th.start()
        for th in threads: th.join(timeout=PING_TIMEOUT + 1)
        lines = [
            f"- {p['name']} ({p['ip']}) [{p.get('location', '?')}]: {'🟢 Online' if results.get(p['ip']) else '🔴 Offline'}"
            for p in printers
        ]
        return "\n".join(lines)

    if name == "ping_device":
        ip = inp.get("ip", "").strip()
        if not ip:
            return "Error: no IP provided."
        ok = _server_monitor.ping_server(ip)
        return f"Ping {ip}: {'✅ Reachable' if ok else '❌ Unreachable'}"

    if name == "restart_server":
        if not sess.get("is_admin"):
            return "❌ Permission denied — only administrators can restart servers."
        ip = inp.get("ip", "").strip()
        server = next((s for s in SERVERS if s["ip"] == ip), None)
        if not server:
            return f"❌ No server found with IP {ip}."
        ok, msg = _ssh_manager.restart_server(server)
        log_event("restart_executed", {"user": sess["user"], "server": server["name"], "ip": ip, "success": ok, "source": "ai"})
        return f"{'✅ Restart initiated' if ok else '❌ Restart failed'}: {msg}"

    if name == "get_printer_install_link":
        ip = inp.get("ip", "").strip()
        os_slot = inp.get("os_slot", "win11")
        printers = _load_printers()
        printer = next((p for p in printers if p["ip"] == ip), None)
        if not printer:
            return f"❌ No printer found with IP {ip}."
        url = f"/api/printers/{ip}/install.ps1?os_slot={os_slot}"
        return f"✅ Download link for {printer['name']} ({os_slot}): {url}\nTell the user to open this URL in the browser to download, then run the .ps1 file as Administrator."

    if name == "search_wiki":
        query = inp.get("query", "")
        results = wiki_db.search_articles(query)[:5]
        if not results:
            return "No wiki articles found."
        return "\n".join([f"- [{r['title']}] ({r['cat_slug']}/{r['slug']}): {r.get('excerpt', '')}" for r in results])

    if name == "get_wiki_article":
        art = wiki_db.get_article(inp.get("cat_slug", ""), inp.get("art_slug", ""))
        if not art:
            return "Article not found."
        return f"# {art['title']}\n\n{art.get('content', art.get('body', ''))}"

    if name == "create_wiki_category":
        cat_name = (inp.get("name") or "").strip()
        if not cat_name:
            return "Error: name is required."
        desc = (inp.get("description") or "").strip()
        cat = wiki_db.create_category(cat_name, desc)
        return f"✅ Category '{cat['name']}' created (slug: {cat['slug']})."

    if name == "create_wiki_article":
        cat_slug = (inp.get("cat_slug") or "").strip()
        title    = (inp.get("title") or "").strip()
        content  = (inp.get("content") or "").strip()
        tags     = inp.get("tags") or []
        if not cat_slug or not title or not content:
            return "Error: cat_slug, title, and content are required."
        if not wiki_db.get_category(cat_slug):
            return f"Error: category '{cat_slug}' does not exist — create it first."
        art = wiki_db.create_article(cat_slug, title, content, sess.get("user", "ai"), tags)
        return f"✅ Article '{art['title']}' created (slug: {art['slug']}) in category '{cat_slug}'."

    if name == "update_wiki_article":
        cat_slug = (inp.get("cat_slug") or "").strip()
        art_slug = (inp.get("art_slug") or "").strip()
        title    = (inp.get("title") or "").strip()
        content  = (inp.get("content") or "").strip()
        tags     = inp.get("tags") or []
        if not cat_slug or not art_slug or not title or not content:
            return "Error: cat_slug, art_slug, title, and content are required."
        art = wiki_db.update_article(cat_slug, art_slug, title, content, sess.get("user", "ai"), tags)
        if not art:
            return f"Error: article '{cat_slug}/{art_slug}' not found."
        return f"✅ Article '{art['title']}' updated."

    return f"Unknown tool: {name}"


@app.get("/api/chat/status")
async def chat_status(request: Request) -> Dict[str, Any]:
    _require_session(request)
    has_key = bool(
        os.environ.get("AI_API_KEY")
        or (callable(_secure_get_setting) and _secure_get_setting("AI_API_KEY"))
    )
    return {"available": _AI_AVAILABLE, "has_key": has_key}


@app.post("/api/chat/key")
async def save_chat_key(request: Request) -> Dict[str, Any]:
    sess = _require_admin(request)
    body = await request.json()
    key = (body.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key is required")
    if callable(_secure_set_setting):
        _secure_set_setting("AI_API_KEY", key)
    os.environ["AI_API_KEY"] = key
    global _anthropic_client, _AI_AVAILABLE
    try:
        import anthropic as _anthropic
        _anthropic_client = _anthropic.Anthropic(api_key=key)
        _AI_AVAILABLE = True
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    log_event("ai_key_saved", {"user": sess["user"]})
    return {"ok": True}


@app.get("/api/chat/conversations")
async def list_conversations(request: Request) -> List[Dict[str, Any]]:
    sess = _require_session(request)
    return chat_db.list_conversations(sess["user"])


@app.post("/api/chat/conversations")
async def create_conversation(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    body = await request.json()
    title = (body.get("title") or "New conversation")[:80]
    cid = chat_db.create_conversation(sess["user"], title)
    return {"id": cid, "title": title}


@app.patch("/api/chat/conversations/{cid}")
async def rename_conversation(cid: int, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    body = await request.json()
    title = (body.get("title") or "").strip()[:80]
    if not title:
        raise HTTPException(status_code=400, detail="Title required")
    chat_db.rename_conversation(cid, sess["user"], title)
    return {"ok": True}


@app.delete("/api/chat/conversations/{cid}")
async def delete_conversation(cid: int, request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    chat_db.delete_conversation(cid, sess["user"])
    return {"ok": True}


@app.get("/api/chat/history")
async def get_chat_history(request: Request,
                           conv: Optional[int] = None) -> List[Dict[str, Any]]:
    sess = _require_session(request)
    if conv is None:
        raise HTTPException(status_code=400, detail="conv parameter required")
    return chat_db.get_history(sess["user"], conv)


@app.delete("/api/chat/history")
async def clear_chat_history(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    chat_db.clear_history(sess["user"])
    return {"ok": True}


@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    sess = _require_session(request)
    if not _AI_AVAILABLE or not _anthropic_client:
        raise HTTPException(status_code=503, detail="AI not configured — add an API key in Settings")
    body = await request.json()
    messages: List[Dict] = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    user = sess["user"]
    conv_id: Optional[int] = body.get("conversation_id")
    mode = body.get("mode", "normal")
    system_prompt = (
        _build_wiki_interview_prompt(sess) if mode == "wiki_interview"
        else _build_system_prompt(sess)
    )

    # Save the new user message (last in the list)
    last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), None)
    if last_user_msg and conv_id:
        try:
            chat_db.save_message(user, "user", last_user_msg, conv_id)
            # Auto-title: if this is the first message, derive title from it
            if len([m for m in messages if m["role"] == "user"]) == 1:
                auto_title = last_user_msg[:60].strip()
                if len(last_user_msg) > 60:
                    auto_title += "…"
                chat_db.rename_conversation(conv_id, user, auto_title)
        except Exception:
            pass

    async def _generate():
        import anthropic as _anthropic
        import re as _re
        current_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
        full_text = ""
        total_in = 0
        total_out = 0

        try:
            while True:
                with _anthropic_client.messages.stream(
                    model="claude-opus-4-5",
                    max_tokens=2048,
                    system=system_prompt,
                    tools=_AI_TOOLS,
                    messages=current_messages,
                ) as stream:
                    for event in stream:
                        et = getattr(event, "type", None)
                        if et == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            if getattr(delta, "type", None) == "text_delta":
                                full_text += delta.text
                                yield f"data: {json.dumps({'type': 'text', 'text': delta.text})}\n\n"
                    final_msg = stream.get_final_message()

                if hasattr(final_msg, "usage") and final_msg.usage:
                    total_in  += getattr(final_msg.usage, "input_tokens",  0)
                    total_out += getattr(final_msg.usage, "output_tokens", 0)

                full_content = final_msg.content
                stop_reason  = final_msg.stop_reason

                if stop_reason == "tool_use":
                    current_messages.append({"role": "assistant", "content": full_content})
                    tool_results = []
                    for block in full_content:
                        if getattr(block, "type", None) == "tool_use":
                            yield f"data: {json.dumps({'type': 'tool_call', 'tool': block.name, 'input': block.input})}\n\n"
                            result = await _execute_ai_tool(block.name, block.input, sess)
                            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
                            yield f"data: {json.dumps({'type': 'tool_result', 'tool': block.name, 'result': result})}\n\n"
                    current_messages.append({"role": "user", "content": tool_results})
                else:
                    break

        except Exception as e:
            err = str(e)
            if "usage limits" in err or "You have reached" in err:
                m = _re.search(r"\d{4}-\d{2}-\d{2}", err)
                date_str = f" El acceso se recuperará el **{m.group(0)}**." if m else ""
                msg = f"⚠️ Se ha alcanzado el límite de uso mensual de la API de Claude (Anthropic).{date_str} Contacta al administrador o espera al siguiente ciclo de facturación."
            elif "401" in err or "authentication" in err.lower():
                msg = "⚠️ Clave de API incorrecta o expirada. Configura una nueva en Ajustes."
            elif "429" in err or "rate limit" in err.lower():
                msg = "⚠️ Demasiadas peticiones seguidas. Espera unos segundos e inténtalo de nuevo."
            else:
                msg = f"⚠️ Error de la API: {err[:300]}"
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Token usage — claude-opus-4-5: $15/MTok in · $75/MTok out
        if total_in or total_out:
            cost = (total_in * 15 + total_out * 75) / 1_000_000
            yield f"data: {json.dumps({'type': 'usage', 'input_tokens': total_in, 'output_tokens': total_out, 'cost_usd': round(cost, 5)})}\n\n"

        # Save final assistant response
        if full_text and conv_id:
            try:
                chat_db.save_message(user, "assistant", full_text, conv_id)
            except Exception:
                pass

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Config export / import ────────────────────────────────────────────────────

_NON_SECRET_SETTINGS = {
    "COBALTAX_USERS", "COBALTAX_ADMINS", "LDAP_HOSTS", "LDAP_DOMAIN",
    "LDAP_BASE_DN", "LDAP_ADMIN_GROUP", "LDAP_PORT", "LDAP_USE_SSL",
    "LDAP_STARTTLS", "SSH_BANNER_TIMEOUT", "SSH_AUTH_TIMEOUT",
    "TELEGRAM_DEFAULT_LIMIT", "TELEGRAM_REFRESH_INTERVAL",
    "NETWORK_DESCRIPTION", "printers_list", "monitored_apps", "backup_jobs",
}


@app.get("/api/admin/config/export")
async def export_config(request: Request) -> Response:
    sess = _require_session(request)
    if not _is_admin(sess):
        raise HTTPException(status_code=403, detail="Admin only")

    servers = [
        {k: v for k, v in s.items() if k != "ssh_password"}
        for s in SERVERS
    ]
    settings: Dict[str, str] = {}
    for key in _NON_SECRET_SETTINGS:
        val = _secure_get_setting(key)
        if val is not None:
            settings[key] = val

    payload = {
        "version": 1,
        "exported_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "servers": servers,
        "settings": settings,
        "users": [{"username": u, "is_admin": _secure_is_admin(u) if callable(_secure_is_admin) else False}
                  for u in (_secure_list_users() if callable(_secure_list_users) else [])],
    }
    filename = f"cobaltax_config_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/admin/config/import")
async def import_config(request: Request) -> Dict[str, Any]:
    sess = _require_session(request)
    if not _is_admin(sess):
        raise HTTPException(status_code=403, detail="Admin only")

    data = await request.json()
    if data.get("version") != 1:
        raise HTTPException(status_code=400, detail="Unsupported config version")

    imported: Dict[str, int] = {"servers": 0, "settings": 0, "users": 0}

    # Servers (no passwords — those must be set separately)
    for s in data.get("servers", []):
        if not s.get("ip"):
            continue
        try:
            from secure_config_store import upsert_server as _upsert_srv
            _upsert_srv(s)
            imported["servers"] += 1
        except Exception:
            pass

    # Settings
    for key, val in data.get("settings", {}).items():
        if key in _NON_SECRET_SETTINGS and val:
            try:
                _secure_set_setting(key, str(val), secret=False)
                imported["settings"] += 1
            except Exception:
                pass

    # Users (no passwords)
    for u in data.get("users", []):
        username = u.get("username")
        if not username:
            continue
        try:
            from secure_config_store import upsert_user as _upsert_usr
            _upsert_usr(username, None, is_admin_flag=bool(u.get("is_admin")))
            imported["users"] += 1
        except Exception:
            pass

    log_event("config_imported", imported, user=sess.get("user"))
    return {"ok": True, "imported": imported,
            "note": "Passwords were not imported — set them via Settings after import."}


def run(host: str = "0.0.0.0", port: int = 8080) -> None:
    print(f"CobaltaX Server Monitor starting at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
