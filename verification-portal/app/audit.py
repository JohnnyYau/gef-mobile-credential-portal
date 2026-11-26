"""audit.py — administrative audit trail (batch U3.3).

Separate from the anonymised public verification log on purpose: the public log
answers "what was verified" (hash prefix only, no operator), the audit trail
answers "who did what to the system" (issuing, revoking, key and signer
management).

U9-B adds the "who": the request middleware resolves the caller (API-key id,
admin/issuer role, or anonymous) and stashes it in a context variable, so
`record()` keeps its signature and every existing call site automatically
records the operator. The value is per-request: the middleware resets it in
`finally`, and a fresh request never inherits the previous caller.

Records go through ``repository.store("audit")`` so both storage backends
cover them. Writing an audit event must never break the request it describes:
storage failures are swallowed inside the store, exactly like the JSON
notification log.
"""

from contextvars import ContextVar

from . import repository
from .config import AUDIT_RECENT_LIMIT

ANONYMOUS = "anonymous"

_ACTOR: ContextVar[str] = ContextVar("gef_audit_actor", default=ANONYMOUS)


def set_actor(actor: str) -> None:
    """Bind the caller identity for the current request context."""
    _ACTOR.set(actor or ANONYMOUS)


def clear_actor() -> None:
    """Forget the caller (also used between tests and at request teardown)."""
    _ACTOR.set(ANONYMOUS)


def current_actor() -> str:
    return _ACTOR.get()


def record(action: str, subject: str | None = None, outcome: str = "ok",
           detail: str | None = None) -> dict:
    """Append one event. ``subject`` is the hash / key id / signer fingerprint."""
    return repository.store("audit").record(action, subject, outcome, detail)


def recent(limit: int = AUDIT_RECENT_LIMIT) -> list:
    return repository.store("audit").recent(limit)
