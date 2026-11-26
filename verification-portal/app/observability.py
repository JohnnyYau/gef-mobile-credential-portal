"""Request-scoped observability: correlation id, structured logs, counters.

Batch U7.2. Three rules drive every choice here:

1. **A request id must exist even when the request is rejected early.** The
   harden middleware returns 403/413/429 before routing, so the id is minted
   at the top of that middleware and returned in ``X-Request-ID`` on every
   path, including the rejections.
2. **Logs are JSON lines, never f-strings with user data thrown in.** One
   record per request: level, endpoint, status, duration, and (for a
   verification) the verdict plus chain height. Field values are redacted
   before they are serialised, so a hash or an e-mail cannot leak by
   accident, and the redaction list lives in one place.
3. **Counters are in-process.** This is a single-node demo: a process-local
   counter is honest about what it measures. Multi-worker aggregates need
   the same seam as the rate limiter — see ``TODO[external-redis]`` in
   ``rate_limit.py``; ``counters.shared_across_workers == False`` says so in
   the payload rather than pretending.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import Counter
from typing import Any

REQUEST_ID_HEADER = "X-Request-ID"
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="")

logger = logging.getLogger("portal.access")
if not logger.handlers:                      # do not fight the app's own config
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(os.environ.get("PORTAL_LOG_LEVEL", "INFO").upper())
logger.propagate = False

# Keys whose values must never reach a log line. Matching is by exact key so
# that a field called ``hash_prefix`` (already truncated by the caller) stays
# readable while ``hashed_document`` does not.
SENSITIVE_KEYS = frozenset({
    "hashed_document", "hash", "credential_hash", "document",
    "email", "student_email", "student_id", "dob", "date_of_birth",
    "token", "admin_token", "issuer_token", "authorization",
    "api_key", "key", "password", "secret", "smtp_password",
})


def new_request_id() -> str:
    """Mint a correlation id: 16 hex chars, no dependency on the clock alone."""
    return secrets.token_hex(8)


def accept_request_id(candidate: str | None) -> str:
    """Use the caller's id when it is opaque and safe, otherwise mint one.

    Rejecting a malformed value (rather than sanitising it) keeps log
    correlation honest: a rewritten id no longer identifies the caller's
    original request.
    """
    if candidate and _CLIENT_ID_RE.match(candidate):
        return candidate
    return new_request_id()


def current_request_id() -> str:
    return _request_id.get()


def bind_request_id(value: str) -> None:
    _request_id.set(value)


def redact(key: str, value: Any) -> Any:
    """Mask sensitive values, keep the shape readable."""
    if value is None:
        return None
    if key in SENSITIVE_KEYS:
        text = str(value)
        if key in ("hashed_document", "hash", "credential_hash"):
            return text[:8] + "…" if len(text) > 8 else "…"
        if "@" in text:                        # e-mail
            local, _, domain = text.partition("@")
            return (local[:1] + "***@" + domain) if domain else "***"
        return "***"
    return value


def log_event(level: str, event: str, **fields: Any) -> None:
    """Emit one JSON line. Duration is rounded to whole milliseconds."""
    payload: dict[str, Any] = {
        "ts": round(time.time(), 3),
        "level": level,
        "event": event,
        "request_id": current_request_id() or "-",
    }
    for key, value in fields.items():
        payload[key] = redact(key, value)
    logger.log(getattr(logging, level.upper(), logging.INFO),
               json.dumps(payload, ensure_ascii=False, default=str))


class Counters:
    """In-process counters for the metrics endpoint."""

    shared_across_workers = False

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.requests: Counter[tuple[str, int]] = Counter()
        self.verdicts: Counter[str] = Counter()
        self.rate_limit_denied = 0
        self.origin_denied = 0
        self.body_too_large = 0
        self.verification_total = 0
        self.duration_ms_total = 0

    def record_request(self, endpoint: str, status: int, duration_ms: int) -> None:
        with self._lock:
            self.requests[(endpoint, status)] += 1
            self.duration_ms_total += duration_ms

    def record_verification(self, verdict: str | None) -> None:
        with self._lock:
            self.verification_total += 1
            self.verdicts[(verdict or "UNKNOWN").upper()] += 1

    def record_denial(self, kind: str) -> None:
        """Count a rejection that never reached the router."""
        with self._lock:
            if kind == "rate_limit":
                self.rate_limit_denied += 1
            elif kind == "origin":
                self.origin_denied += 1
            elif kind == "body_too_large":
                self.body_too_large += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = sum(self.requests.values())
            reqs = [
                {"endpoint": endpoint, "status": status, "count": count}
                for (endpoint, status), count in sorted(self.requests.items())
            ]
            verdicts = dict(sorted(self.verdicts.items()))
            avg = round(self.duration_ms_total / total, 1) if total else 0.0
            return {
                "requests_total": total,
                "requests": reqs,
                "avg_duration_ms": avg,
                "verifications_total": self.verification_total,
                "verdict_distribution": verdicts,
                "denied": {
                    "rate_limit": self.rate_limit_denied,
                    "origin": self.origin_denied,
                    "body_too_large": self.body_too_large,
                },
                "uptime_s": round(time.time() - self.started_at, 1),
                "shared_across_workers": self.shared_across_workers,
            }

    def reset(self) -> None:
        """Tests need a known starting point; not exposed over HTTP."""
        with self._lock:
            self.requests.clear()
            self.verdicts.clear()
            self.rate_limit_denied = 0
            self.origin_denied = 0
            self.body_too_large = 0
            self.verification_total = 0
            self.duration_ms_total = 0
            self.started_at = time.time()


COUNTERS = Counters()
