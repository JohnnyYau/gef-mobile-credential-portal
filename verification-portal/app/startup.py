"""startup.py — boot-time configuration validation (batch U8.2).

The portal reads ~30 settings from the environment at import time. Historically
a typo'd value surfaced as a *runtime* symptom far from its cause: `STORAGE_
BACKEND=sqlitee` silently fell back to JSON, `EMAIL_ENABLED=1` without
`SMTP_HOST` produced "sent" notifications that never left the box, and a
non-writable `CHAIN_DIR` only failed on the first issuance.

``validate_config()`` turns those into one report at boot:

    fatal    — refuse to start. The process cannot serve correct answers.
    warnings — start anyway, but say what is degraded and why.

The distinction is deliberate: a demo must not fail to boot because a mail
server is missing (dry-run is a documented mode), but it must not boot on a
storage backend it does not implement, or on a chain directory it cannot write
to — in both cases every "VALID" verdict would be a lie about data that was
never persisted.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

VALID_BACKENDS = ("json", "sqlite")
VALID_SESSION_BACKENDS = ("memory", "redis")
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return os.access(path, os.W_OK)
    except OSError:
        return False


def validate_config(cfg: Any) -> dict[str, list[str]]:
    """Inspect the imported config object; returns {"fatal": [...], "warnings": [...]}.

    Takes the config module as an argument rather than importing it, so tests
    can validate hypothetical configurations without reloading the app.
    """
    fatal: list[str] = []
    warnings: list[str] = []

    backend = (cfg.STORAGE_BACKEND or "").lower()
    if backend not in VALID_BACKENDS:
        fatal.append(
            f"STORAGE_BACKEND={cfg.STORAGE_BACKEND!r} is not implemented "
            f"(valid: {', '.join(VALID_BACKENDS)})")

    chain_dir = Path(cfg.CHAIN_DIR)
    if not _writable_dir(chain_dir.parent):
        fatal.append(f"CHAIN_DIR parent is not writable: {chain_dir.parent}")
    if backend == "sqlite":
        sqlite_path = Path(cfg.SQLITE_PATH)
        if not _writable_dir(sqlite_path.parent):
            fatal.append(f"SQLITE_PATH parent is not writable: {sqlite_path.parent}")

    if not Path(cfg.STATIC_DIR).is_dir():
        warnings.append(
            f"STATIC_DIR missing: {cfg.STATIC_DIR} — the UI will 404 while "
            "the API still works")

    session_backend = (cfg.SESSION_BACKEND or "").lower()
    if session_backend not in VALID_SESSION_BACKENDS:
        warnings.append(
            f"SESSION_BACKEND={cfg.SESSION_BACKEND!r} is unknown; "
            "chat sessions fall back to the in-process store")
    elif session_backend == "redis":
        warnings.append(
            "SESSION_BACKEND=redis is a placeholder (TODO[external-redis]); "
            "sessions stay in process memory")

    if cfg.PUBLIC_MODE and cfg.ADMIN_TOKEN:
        warnings.append(
            "PUBLIC_MODE=1 makes every admin endpoint 403, so ADMIN_TOKEN has "
            "no effect on this instance")

    if cfg.EMAIL_ENABLED and not cfg.SMTP_HOST:
        warnings.append(
            "EMAIL_ENABLED=1 without SMTP_HOST — notifications are recorded as "
            "dry-run and never leave the machine")

    # U10: signer key at rest. Absence of a passphrase is the historical demo
    # default (plaintext PKCS#8), so it is a warning, never fatal — but the
    # boot log should say it out loud, and a key on disk that does not match
    # the configured passphrase must not be papered over.
    passphrase = getattr(cfg, "SIGNER_KEY_PASSPHRASE", "") or ""
    keys_dir = chain_dir / "keys"
    key_files = sorted(keys_dir.glob("*.priv.pem")) if keys_dir.is_dir() else []
    if not passphrase:
        if key_files:
            warnings.append(
                f"GEF_KEY_PASSPHRASE is unset and {len(key_files)} signer "
                "private key file(s) are stored unencrypted under "
                f"{keys_dir} — set GEF_KEY_PASSPHRASE to encrypt them at rest")
    elif key_files:
        plaintext = [p.name for p in key_files
                     if b"ENCRYPTED PRIVATE KEY" not in p.read_bytes()[:64]]
        if plaintext:
            warnings.append(
                "GEF_KEY_PASSPHRASE is set but these key files are still "
                f"plaintext and will be re-encrypted on first load: "
                f"{', '.join(plaintext)}")

    if cfg.CHAIN_SNAPSHOT_URL and Path(cfg.CHAIN_DIR).exists() and any(
            Path(cfg.CHAIN_DIR).iterdir()):
        warnings.append(
            "CHAIN_SNAPSHOT_URL is set but CHAIN_DIR is not empty — the "
            "snapshot is ignored (restore only seeds a fresh instance)")

    if (cfg.RATE_LIMIT_ENABLED and cfg.RATE_LIMIT_PUBLIC_MAX <= 0
            and cfg.RATE_LIMIT_ADMIN_MAX <= 0):
        warnings.append(
            "both RATE_LIMIT_*_MAX are <= 0: the limiter allows everything")

    origins = (cfg.ALLOWED_ORIGINS or "").strip()
    base = (cfg.PUBLIC_BASE_URL or "").strip()
    if not origins and base.startswith("https://") and "127.0.0.1" not in base:
        warnings.append(
            "ALLOWED_ORIGINS is empty while PUBLIC_BASE_URL is a public https "
            "URL: browser POSTs from any other host will be rejected (403)")

    level = os.environ.get("PORTAL_LOG_LEVEL", "INFO").upper()
    if level not in VALID_LOG_LEVELS:
        warnings.append(
            f"PORTAL_LOG_LEVEL={level!r} is not a logging level; INFO is used")

    # U24: `TRUSTED_PROXIES` decides whether X-Forwarded-For is believed. A
    # typo there must be loud: "trust nobody" silently reverts every user
    # behind a proxy into one shared bucket, and the operator would only
    # notice when the whole office is locked out.
    raw_proxies = (getattr(cfg, "TRUSTED_PROXIES", "") or "").strip()
    if raw_proxies:
        import ipaddress
        bad = []
        for part in raw_proxies.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ipaddress.ip_network(part, strict=False)
            except ValueError:
                bad.append(part)
        if bad:
            warnings.append(
                "TRUSTED_PROXIES contains entries that are not an IP or CIDR: "
                f"{', '.join(bad)} — those are ignored, so requests arriving "
                "through them are bucketed by the proxy address instead")

    return {"fatal": fatal, "warnings": warnings}


def describe(report: dict[str, list[str]]) -> str:
    """One operator-facing line per problem, suitable for a log."""
    lines = [f"fatal: {line}" for line in report["fatal"]]
    lines += [f"warning: {line}" for line in report["warnings"]]
    return "\n".join(lines)
