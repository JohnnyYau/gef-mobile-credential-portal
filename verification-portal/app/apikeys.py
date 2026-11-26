"""Public verification API keys (employer pack, extras round 6).

Key lifecycle lives here: create (admin-gated in main.py), list, revoke.
Only a SHA-256 digest of each key is stored, so the store is not a credential
leak. Rate limiting keys off the validated key via the digest — the limiter
runs in the request path, not here.

Since batch U2 this module is a thin facade over ``repository``: the JSON
file layout is unchanged, and switching ``STORAGE_BACKEND`` to ``sqlite``
moves the same records into a table without touching this API.
"""

from . import repository


def create_key(name: str, expires_in_days: int | None = None) -> dict:
    """Create a key; the raw secret is returned exactly once."""
    return repository.store("api_keys").create_key(name, expires_in_days)


def list_keys() -> list:
    """Public view of keys — never includes the hash or the raw key."""
    return repository.store("api_keys").list_keys()


def revoke_key(kid: str, reason: str | None = None) -> bool:
    return repository.store("api_keys").revoke_key(kid, reason)


def rotate_key(kid: str, expires_in_days: int | None = None):
    """Revoke ``kid`` and issue its replacement in one step (None if not live)."""
    return repository.store("api_keys").rotate_key(kid, expires_in_days)


def validate_key(key: str):
    """Return the key id when ``key`` is a live API key, else None.

    Touches ``last_used_at`` on a hit — the store decides where that lands.
    """
    return repository.store("api_keys").validate_key(key)
