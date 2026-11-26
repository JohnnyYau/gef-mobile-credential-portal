"""authz.py — roles and endpoint authorisation (batch U3.1).

Three roles, deliberately coarse:

    admin     issue, revoke, signer management, API-key management
    issuer    bulk issuing only (the registrar batch wizard)
    verifier  public verification + API (no token: these routes are open)

Resolution is by shared secret, because the deployment is a single demo
instance. ``ADMIN_TOKEN`` keeps working exactly as before; ``ISSUER_TOKEN``
optionally opens the bulk-issue route to a narrower credential.

Backward compatibility rule (important): when **neither** token is configured,
the dependency allows the request, which is precisely what the pre-U3
``_admin_required`` did. Behaviour only changes for an operator who opts in by
setting ``ISSUER_TOKEN``.
"""

from collections.abc import Iterable
import secrets
import time

from fastapi import Header, HTTPException, Request

from . import config as cfg
from .session_store import InMemorySessionStore

ADMIN = "admin"
ISSUER = "issuer"
VERIFIER = "verifier"

ROLE_HEADER = "X-Admin-Token"  # kept: clients already send this header

# U12 R2: staff console sessions. Separate store from the chat sessions so an
# LRU eviction of a chat session can never log a registrar out mid-demo.
STAFF_COOKIE = "staff_sid"
STAFF_SESSION_TTL = 1800          # 30 minutes
# U14: at most this many live console sessions per role. The 4th login evicts
# the oldest, so a forgotten browser tab cannot hold a role open forever.
STAFF_SESSIONS_PER_ROLE = 3
_staff_sessions = InMemorySessionStore(limit=50)

# U14: brute-force brake on the login form. Five wrong tokens from one address
# inside the window and the sixth attempt is refused before the token is read.
LOGIN_FAIL_WINDOW = 600
LOGIN_FAIL_MAX = 5
_login_failures: dict[str, list[float]] = {}


def create_staff_session(role: str, limit: int | None = None) -> str:
    """Open a session and return the opaque id that goes into the cookie."""
    sid = secrets.token_urlsafe(32)
    _staff_sessions.set(sid, {"role": role, "ts": time.time()})
    _evict_oldest_for_role(role, limit)
    return sid


def _evict_oldest_for_role(role: str, limit: int | None = None) -> int:
    """Keep at most ``limit`` sessions for ``role``; returns how many dropped."""
    cap = STAFF_SESSIONS_PER_ROLE if limit is None else int(limit)
    if cap <= 0:
        return 0
    mine = [(sid, e) for sid, e in _staff_sessions.items()
            if (e or {}).get("role") == role]
    dropped = 0
    while len(mine) > cap:
        sid, _ = mine.pop(0)
        _staff_sessions.delete(sid)
        dropped += 1
    return dropped


def drop_staff_sessions(role: str | None = None) -> int:
    """Drop every console session (or every session of one role).

    U14 F6: "sign out everywhere". Called by ``POST /staff/logout/all`` after
    the caller's own role is resolved from the cookie.
    """
    dropped = 0
    for sid, entry in _staff_sessions.items():
        if role is None or (entry or {}).get("role") == role:
            _staff_sessions.delete(sid)
            dropped += 1
    return dropped


def login_allowed(key: str) -> bool:
    """True while this client still has attempts left (U14 F6)."""
    now = time.time()
    window = [ts for ts in _login_failures.get(key, []) if now - ts < LOGIN_FAIL_WINDOW]
    _login_failures[key] = window
    return len(window) < LOGIN_FAIL_MAX


def note_login_failure(key: str) -> None:
    now = time.time()
    window = [ts for ts in _login_failures.get(key, []) if now - ts < LOGIN_FAIL_WINDOW]
    window.append(now)
    _login_failures[key] = window


def clear_login_failures(key: str) -> None:
    _login_failures.pop(key, None)


def read_staff_session(sid: str | None) -> str | None:
    """Role held by ``sid``, or None when missing, expired or unknown."""
    if not sid:
        return None
    entry = _staff_sessions.get(sid)
    if not entry:
        return None
    if time.time() - float(entry.get("ts", 0)) > STAFF_SESSION_TTL:
        drop_staff_session(sid)
        return None
    entry["ts"] = time.time()  # sliding expiry on use
    return entry.get("role")


def drop_staff_session(sid: str | None) -> None:
    if sid:
        _staff_sessions.delete(sid)


def staff_session_remaining(sid: str | None) -> int | None:
    """Seconds left on a staff session, or None when missing or unknown.

    U13 F6: the console shows a countdown, so a registrar is never surprised
    mid-batch by a quiet 30-minute expiry.
    """
    if not sid:
        return None
    entry = _staff_sessions.get(sid)
    if not entry:
        return None
    left = STAFF_SESSION_TTL - (time.time() - float(entry.get("ts", 0)))
    return max(0, int(left))


def _token_for(role: str) -> str:
    # ADMIN_TOKEN defaults to None; coerce to "" explicitly. Plain str(None)
    # would yield "None" and make an unset token look configured.
    if role == ADMIN:
        return cfg.ADMIN_TOKEN or ""
    if role == ISSUER:
        return cfg.ISSUER_TOKEN or ""
    return ""


def configured_roles(roles: Iterable[str]) -> dict:
    """Roles among ``roles`` that actually have a token configured."""
    out = {}
    for role in roles:
        token = _token_for(role)
        if token:
            out[role] = token
    return out


def resolve_role(token: str | None, roles: Iterable[str] | None = None) -> str | None:
    """Role whose configured token matches ``token`` (None when it matches none)."""
    if not token:
        return None
    candidates = configured_roles(tuple(roles) if roles else (ADMIN, ISSUER))
    for role, secret in candidates.items():
        if token == secret:
            return role
    return None


def check_roles(allowed, request: Request | None = None,
                token: str | None = None):
    """The single body shared by every entry point that gates a role.

    403 in public mode, demo-open when nothing is configured, then a header
    token, then a browser session. Callers that have a ``Request`` pass it so
    the session cookie is honoured; pure-CLI callers may pass only a token.
    """
    if cfg.PUBLIC_MODE:
        raise HTTPException(
            status_code=403,
            detail="Admin functions are disabled in public verifier mode. "
                   "Run a private instance (PUBLIC_MODE=0) behind auth to "
                   "issue or revoke credentials.")
    if not configured_roles(allowed):
        # No token configured for these roles. U13 F7: this used to let the
        # request through silently; now it is an explicit DEMO_OPEN switch.
        if cfg.DEMO_OPEN:
            return None
        raise HTTPException(
            status_code=401,
            detail="No role token is configured on this instance and "
                   "DEMO_OPEN=0, so admin routes are closed. Set ADMIN_TOKEN "
                   "or ISSUER_TOKEN to use them.")
    role = resolve_role(token, allowed)
    if role is not None:
        return role
    # U12 R2: a browser session opened at /staff/login is an equally valid
    # credential, so the staff console's own fetch() calls need no header.
    if request is not None:
        role = read_staff_session(request.cookies.get(STAFF_COOKIE))
        if role is not None and role in allowed:
            return role
    raise HTTPException(
        status_code=401,
        detail="Missing or invalid X-Admin-Token header.")


def require_roles(*roles: str):
    """FastAPI dependency factory: 403 in public mode, 401 on a bad credential."""
    allowed = tuple(roles)

    def dependency(request: Request,
                   x_admin_token: str | None = Header(default=None,
                                                     alias=ROLE_HEADER)):
        return check_roles(allowed, request, x_admin_token)

    return dependency
