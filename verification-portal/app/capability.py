"""capability.py — signed, expiring links that carry one holder's own data.

Batch U12 R3. The public page used to accept ``StudentID + DOB`` and return
every credential held by that student. That is an enumerable privacy gate:
a DOB is eight digits, the endpoint had no token and no rate limit, and its
error messages distinguished "wrong DOB" from "unknown student".

A capability link replaces the guessable pair with something only the issuer
can hand out:

    /me/<token>        holder page
    /api/me/<token>    that holder's credentials

    token   = b64url(payload) "." b64url(HMAC-SHA256(secret, b64url(payload)))
    payload = {"sid": ..., "h": ..., "exp": ..., "v": 1}

Forging needs the secret; expiry lives in the signed payload, so there is no
server-side table to keep or to leak. Revocation is not baked in: the holder
view re-reads chain status on every request, so a revoked credential turns
REVOKED here immediately without reissuing the link.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time

from . import config as cfg

logger = logging.getLogger("capability")

VERSION = 1
MIN_TTL = 300          # 5 minutes: shorter links are a mistake, not a feature
MAX_TTL = 365 * 24 * 3600

_ephemeral_secret: bytes | None = None


def _secret() -> bytes:
    global _ephemeral_secret
    if cfg.CAPABILITY_SECRET:
        return cfg.CAPABILITY_SECRET.encode("utf-8")
    if cfg.ADMIN_TOKEN:
        return ("cap:" + cfg.ADMIN_TOKEN).encode("utf-8")
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_bytes(32)
        logger.warning(
            "CAPABILITY_SECRET is unset and so is ADMIN_TOKEN: holder links are "
            "signed with a per-process key and will stop working on restart.")
    return _ephemeral_secret


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(body: str) -> str:
    return _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())


def mint(student_id: str, hashed_document: str, ttl: int | None = None) -> str:
    """Return a link token for one credential.

    ``hashed_document`` scopes the link to a single credential, so a leaked
    link cannot enumerate the rest of that student's records.
    """
    sid = str(student_id or "").strip()
    hashed = str(hashed_document or "").strip()
    if not sid or not hashed:
        raise ValueError("student_id and hashed_document are required")
    seconds = int(ttl if ttl is not None else cfg.CAPABILITY_TTL)
    seconds = max(MIN_TTL, min(seconds, MAX_TTL))
    payload = {
        "sid": sid,
        "h": hashed,
        "exp": int(time.time()) + seconds,
        "v": VERSION,
    }
    body = _b64(json.dumps(payload, separators=(",", ":"),
                           sort_keys=True).encode("utf-8"))
    return body + "." + _sign(body)


def parse(token: str) -> dict | None:
    """Verified payload, or None for malformed, tampered or expired tokens.

    One return value for every failure: callers answer 404 in all cases, so
    the response cannot be used to probe whether a token "almost" worked.
    """
    raw = str(token or "").strip()
    if not raw or len(raw) > 2048 or raw.count(".") != 1:
        return None
    body, sig = raw.split(".", 1)
    try:
        expected = _sign(body)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("v") != VERSION:
        return None
    if not payload.get("sid") or not payload.get("h"):
        return None
    try:
        expires = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        return None
    if expires < int(time.time()):
        return None
    payload["exp"] = expires
    return payload
