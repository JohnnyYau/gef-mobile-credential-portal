"""Public verification API keys (employer pack, extras round 6).

Key lifecycle lives here: create (admin-gated in main.py), list, revoke.
Only a SHA-256 digest of each key is stored (``data/apikeys.json``), so the
store is not a credential leak. Rate limiting keys off the validated key via
``rate_key()`` — call it from the request path before the limiter runs.

Demo-scale store (JSON on disk, protected by a lock); a real deployment would
swap this module for a database / secret manager without touching the API.
"""

import hashlib
import json
import os
import secrets
import threading
import time

from . import config as cfg

_KEYS_FILE = cfg.BASE_DIR / "data" / "apikeys.json"
_lock = threading.Lock()


def _load() -> dict:
    try:
        with open(_KEYS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(store: dict) -> None:
    _KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _KEYS_FILE.with_name(_KEYS_FILE.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _KEYS_FILE)


def _digest(key: str) -> str:
    return hashlib.sha256(("gef26-apikey:" + key).encode("utf-8")).hexdigest()


def create_key(name: str) -> dict:
    """Create a key; the raw secret is returned exactly once."""
    key = secrets.token_urlsafe(32)
    kid = secrets.token_hex(3)
    with _lock:
        store = _load()
        store[kid] = {
            "name": (name or "unnamed")[:80],
            "created_at": time.time(),
            "last_used_at": None,
            "revoked": False,
            "hash": _digest(key),
        }
        _save(store)
    return {"id": kid, "name": store[kid]["name"], "key": key,
            "created_at": store[kid]["created_at"]}


def list_keys() -> list:
    """Public view of keys — never includes the hash or the raw key."""
    with _lock:
        store = _load()
        out = []
        for kid, rec in sorted(store.items()):
            out.append({
                "id": kid,
                "name": rec.get("name"),
                "created_at": rec.get("created_at"),
                "last_used_at": rec.get("last_used_at"),
                "revoked": bool(rec.get("revoked")),
            })
        return out


def revoke_key(kid: str) -> bool:
    with _lock:
        store = _load()
        if kid not in store:
            return False
        store[kid]["revoked"] = True
        _save(store)
        return True


def validate_key(key: str):
    """Return the key id when ``key`` is a live API key, else None.
    Touches last_used_at (disk write) on a hit — fine at this scale."""
    if not key:
        return None
    digest = _digest(key)
    with _lock:
        store = _load()
        for kid, rec in store.items():
            if rec.get("hash") == digest:
                if rec.get("revoked"):
                    return None
                rec["last_used_at"] = time.time()
                _save(store)
                return {"id": kid}
        return None
