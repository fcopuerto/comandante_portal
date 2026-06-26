"""Module registry and AD-based permission resolution for Portal Cobaltax."""
from __future__ import annotations

from typing import Any, Dict, List

# Built-in module definitions (order = sidebar order)
BUILTIN_MODULES: List[Dict[str, Any]] = [
    {"id": "health",   "icon": "🖥",  "order": 1},
    {"id": "apps",     "icon": "📦", "order": 2},
    {"id": "printers", "icon": "🖨", "order": 3},
    {"id": "support",  "icon": "🎫", "order": 4},
    {"id": "vpn",      "icon": "🔒", "order": 5},
    {"id": "wiki",     "icon": "📚", "order": 6},
    {"id": "ai",       "icon": "🤖", "order": 7},
    {"id": "energy",        "icon": "⚡", "order": 8},
    {"id": "workstations",  "icon": "💻", "order": 9},
]

_PORTAL_ADMIN_GROUP_KEY = "portal_admin_group"
_DEFAULT_PORTAL_ADMIN = "Portal-Admin"


def _gs(key: str, default: str = "") -> str:
    """Read a setting from secure store with fallback."""
    try:
        from secure_config_store import get_setting
        val = get_setting(key)
        return val if val is not None else default
    except Exception:
        return default


def portal_admin_group() -> str:
    return _gs(_PORTAL_ADMIN_GROUP_KEY, _DEFAULT_PORTAL_ADMIN)


def module_config(module_id: str) -> Dict[str, Any]:
    """Return live config for one module (reads from secure store each call)."""
    cap = module_id.capitalize()
    return {
        "enabled":     _gs(f"module_{module_id}_enabled", "true") != "false",
        "view_group":  _gs(f"module_{module_id}_view_group",  f"Portal-{cap}-View"),
        "admin_group": _gs(f"module_{module_id}_admin_group", f"Portal-{cap}-Admin"),
    }


def resolve_permissions(groups: List[str]) -> Dict[str, str]:
    """Return {module_id: 'admin'|'view'} for every module the user can access.

    If the user is in the portal admin group they get 'admin' on all modules.
    """
    groups_lower = {g.lower() for g in groups}

    # Portal-level admin → unrestricted
    if portal_admin_group().lower() in groups_lower:
        return {m["id"]: "admin" for m in BUILTIN_MODULES}

    perms: Dict[str, str] = {}
    for m in BUILTIN_MODULES:
        mid = m["id"]
        cfg = module_config(mid)
        if not cfg["enabled"]:
            continue
        if cfg["admin_group"].lower() in groups_lower:
            perms[mid] = "admin"
        elif cfg["view_group"].lower() in groups_lower:
            perms[mid] = "view"

    return perms


def all_settings() -> Dict[str, Any]:
    """Return all portal settings as a dict (for the Settings UI)."""
    mods = []
    for m in BUILTIN_MODULES:
        cfg = module_config(m["id"])
        mods.append({"id": m["id"], "icon": m["icon"], **cfg})
    return {
        "portal_name":         _gs("portal_name", "Portal Cobaltax"),
        "portal_admin_group":  portal_admin_group(),
        "default_language":    _gs("default_language", "en"),
        "modules":             mods,
    }


def save_settings(data: Dict[str, Any]) -> None:
    """Persist portal settings to secure store."""
    from secure_config_store import set_setting
    if "portal_name" in data:
        set_setting("portal_name", str(data["portal_name"]))
    if "portal_admin_group" in data:
        set_setting(_PORTAL_ADMIN_GROUP_KEY, str(data["portal_admin_group"]))
    if "default_language" in data:
        set_setting("default_language", str(data["default_language"]))
    for mod in data.get("modules", []):
        mid = mod.get("id")
        if not mid:
            continue
        if "enabled" in mod:
            set_setting(f"module_{mid}_enabled", "true" if mod["enabled"] else "false")
        if "view_group" in mod:
            set_setting(f"module_{mid}_view_group",  str(mod["view_group"]))
        if "admin_group" in mod:
            set_setting(f"module_{mid}_admin_group", str(mod["admin_group"]))
