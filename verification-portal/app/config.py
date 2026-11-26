"""Portal configuration — every value is overridable via environment variables."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # portal root
STATIC_DIR = BASE_DIR / "static"

CHAIN_DIR = Path(os.environ.get("CHAIN_DIR", str(BASE_DIR / "data" / "demo-chain")))
CHAIN_NAME = os.environ.get("CHAIN_NAME", "Gef26-credential-chain")
SIGNER_NAME = os.environ.get("SIGNER_NAME", "UNIVERSITY OF UTOPIA")
SIGNER_ALGO = os.environ.get("SIGNER_ALGO", "ML_DSA_65")

# Optional shared secret for the admin endpoints (POST /api/issue, /api/revoke).
# Leave unset for an open demo; set ADMIN_TOKEN=... to require the header
# `X-Admin-Token: <token>` on admin endpoints.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN") or None

# U13 F7: demo-open becomes an explicit switch instead of an invisible default.
# Previously, an instance with no role token configured let *every* admin route
# through, silently. That is fine on a laptop and unacceptable anywhere else.
#   DEMO_OPEN=1 (default) — old behaviour, but /api/version and the console say
#                           so out loud
#   DEMO_OPEN=0           — fail closed: no configured token means 401
DEMO_OPEN = os.environ.get("DEMO_OPEN", "1") != "0"

# Verify-only UI (round 10): trim the web UI down to the three tabs a verifier
# needs — Verify, AI Chat, Log. Everything else (home/student/admin tabs) is
# hidden and the portal opens straight on the Verify tab. The API surface is
# unchanged; this only shapes the front-end. Applies regardless of PUBLIC_MODE.
UI_VERIFY_ONLY = os.environ.get("UI_VERIFY_ONLY", "0") == "1"

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB upload cap
MAX_JSON_BYTES = 2 * 1024 * 1024    # parsed document JSON cap
MAX_BODY_BYTES = 6 * 1024 * 1024    # request body cap (content-length guard)
MAX_JSON_DEPTH = 50                 # nesting depth cap for uploaded documents

# Week 3 hardening
RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "1") != "0"
RATE_LIMIT_PUBLIC_MAX = int(os.environ.get("RATE_LIMIT_PUBLIC_MAX", "120"))
RATE_LIMIT_ADMIN_MAX = int(os.environ.get("RATE_LIMIT_ADMIN_MAX", "30"))

# Extras round 5: public verifier mode (deploy-time).
# PUBLIC_MODE=1 exposes ONLY the verification surface (verify/student/chat/log)
# plus /api/version and /api/demo/credentials; every admin endpoint returns
# 403 and the UI hides the admin tabs. Admin/issuer functions then live only
# in the private instance or behind real auth.
PUBLIC_MODE = os.environ.get("PUBLIC_MODE", "0") == "1"
APP_VERSION = os.environ.get("APP_VERSION", "6.0.0")

# Post-Week-3 extras
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
ANOMALY_ISSUE_PER_HOUR = int(os.environ.get("ANOMALY_ISSUE_PER_HOUR", "20"))

# UX round: batch issue (registrar wizard). Cap on rows per request.
BATCH_ISSUE_MAX = int(os.environ.get("BATCH_ISSUE_MAX", "200"))

# Self-service credential maker (round 10): where generated PDFs + JSONs are
# saved ("synced to the main project"). Defaults to a folder inside the main
# project dir (three levels above the app package), falling back to a
# portal-local folder when that is not writable.
_CUSTOM_DEFAULT = str(Path(__file__).resolve().parents[3] / "自制凭证-outputs")
CUSTOM_OUTPUT_DIR = os.environ.get("CUSTOM_OUTPUT_DIR", _CUSTOM_DEFAULT)

# Extras round 2: email notifications (dry-run by default — the sandbox has no
# mail server). Set EMAIL_ENABLED=1 + SMTP_* to send real messages.
EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "0") == "1"
SMTP_HOST = os.environ.get("SMTP_HOST") or None
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER") or None
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD") or None
EMAIL_FROM = os.environ.get("EMAIL_FROM") or None

# U12 R4: the recipient of an issue notification is deployment configuration,
# never a value from the request body. Empty NOTIFY_TO means "record the event
# and send nothing" — the safe default for a public demo.
NOTIFY_TO = os.environ.get("NOTIFY_TO", "")
NOTIFY_PER_HOUR = int(os.environ.get("NOTIFY_PER_HOUR", "60"))

# Extras round 4: soft check OCR fallback (scanned PDFs). Requires the system
# `tesseract` binary + `pypdfium2`; when unavailable the soft check reports
# what it could extract from the text layer only.
SOFT_OCR = os.environ.get("SOFT_OCR", "1") == "1"

# Extras round 6 (employer pack): public API keys, signed status list, receipt
# registry. API-key holders get a higher per-minute budget than anonymous web
# users; anonymous stays at RATE_LIMIT_PUBLIC_MAX.
API_KEY_MAX = int(os.environ.get("API_KEY_MAX", "600"))          # per key / min
RECEIPT_REGISTRY_CAP = int(os.environ.get("RECEIPT_REGISTRY_CAP", "5000"))
STATUSLIST_MAX_ENTRIES = int(os.environ.get("STATUSLIST_MAX_ENTRIES", "20000"))

# --------------------------------------------------------------------------
# Operational tunables (internal defaults; not exposed as env overrides)
# --------------------------------------------------------------------------

# Network / backend timeouts, in seconds.
CHAIN_SNAPSHOT_TIMEOUT: int = 60   # chain snapshot restore fetch
LLM_DEEPSEEK_TIMEOUT: int = 40     # DeepSeek API call
LLM_OLLAMA_TIMEOUT: int = 90       # local Ollama call
SMTP_TIMEOUT: int = 10             # SMTP connect/send

# Chain read caches (batch U9-A). Both are invalidated by any block-file
# change (height / size / mtime fingerprint), so the TTL only bounds how long
# a *fingerprint-preserving* on-disk edit could stay invisible; set 0 to disable.
CHAIN_INTEGRITY_TTL: float = float(os.environ.get("CHAIN_INTEGRITY_TTL", "5"))
CHAIN_INDEX_TTL: float = float(os.environ.get("CHAIN_INDEX_TTL", "30"))

# List / row limits.
CHAIN_TAIL_LIMIT: int = 10         # blocks returned by the public chain tail
NOTIFICATION_RECENT_LIMIT: int = 10  # notifications kept in the log view
RAG_CITATION_LIMIT: int = 3        # chain records summarized in an offline answer
MAX_BATCH_DOCUMENTS: int = 500     # documents accepted by POST /api/verify/batch

# Signer private key at rest (batch U10). Empty = the demo's historical
# plaintext PKCS#8 PEM (unchanged default). When set, keys written from now on
# are encrypted with this passphrase (PKCS#8 PBES2, scrypt/AES-256 from
# `cryptography`'s BestAvailableEncryption), and an existing plaintext key is
# re-encrypted in place on first load.
SIGNER_KEY_PASSPHRASE: str = os.environ.get("GEF_KEY_PASSPHRASE", "")

# Truncation caps.
REVOCATION_REASON_MAXLEN: int = 200  # revocation reason stored on-chain
AUDIT_RECENT_LIMIT: int = 50         # events returned by /api/admin/audit

# Role tokens (batch U3.1). ADMIN_TOKEN keeps its existing meaning. ISSUER_TOKEN
# is optional: when set, it opens bulk issuing to a narrower credential.
ISSUER_TOKEN: str = os.environ.get("ISSUER_TOKEN", "")

# Holder capability links (U12 R3). Empty means "derive from ADMIN_TOKEN"; if
# that is also empty the process generates an ephemeral key at startup, so
# links stop working after a restart. Set CAPABILITY_SECRET to make them
# survive restarts (e.g. in a demo box that is redeployed between rehearsals).
CAPABILITY_SECRET: str = os.environ.get("CAPABILITY_SECRET", "")
CAPABILITY_TTL: int = int(os.environ.get("CAPABILITY_TTL", str(30 * 24 * 3600)))
# U14: a holder may renew their own link only in the last week of its life.
# Renewing earlier would just extend how long a leaked link keeps working.
CAPABILITY_RENEW_WINDOW: int = int(os.environ.get("CAPABILITY_RENEW_WINDOW",
                                               str(7 * 24 * 3600)))

# Origins allowed to POST/PUT/PATCH/DELETE (batch U3.4). Same-origin requests
# from the portal's own pages are allowed implicitly; extra hosts (a reverse
# proxy in front of the demo) go here as a comma-separated list.
ALLOWED_ORIGINS: str = os.environ.get("ALLOWED_ORIGINS", "")

# U24: which peers may speak for the client. `X-Forwarded-For` is written by
# the caller, so it is believed only when the direct peer is one of these
# (comma-separated IPs or CIDRs, e.g. "127.0.0.1,10.0.0.0/8"). Empty — the
# default — means the header is ignored entirely and every rate-limit bucket
# is keyed by the real peer address. Before U24 the header was believed
# unconditionally, so any anonymous caller could mint a fresh bucket per
# request (bypassing both limiters) or fill someone else's bucket on purpose.
TRUSTED_PROXIES: str = os.environ.get("TRUSTED_PROXIES", "")

# Storage backend (batch U2.1). "json" keeps the existing on-disk behaviour;
# "sqlite" routes the five stores through app/repository.py. Default stays
# "json" until the endpoint wiring lands in U2.2, so nothing changes yet.
STORAGE_BACKEND: str = os.environ.get("STORAGE_BACKEND", "json").lower()
# Lives beside the chain dir on purpose: tests isolate CHAIN_DIR per module, so
# each module gets its own database without touching SQLITE_PATH explicitly.
# The production default resolves to data/portal.sqlite3, same as before.
SQLITE_PATH: str = os.environ.get(
    "SQLITE_PATH", str(CHAIN_DIR.parent / "portal.sqlite3"))

# Chat session memory (batch U5.3). "memory" is an in-process LRU; the seam
# exists so a multi-worker deploy can swap it without touching the resolver.
SESSION_BACKEND: str = os.environ.get("SESSION_BACKEND", "memory").lower()
SESSION_LIMIT: int = 200           # concurrent chat sessions kept in memory

# Free-tier persistence (extras round 7): CHAIN_SNAPSHOT_URL points at a
# backup_chain.py export. When the chain dir is empty at boot (ephemeral
# storage after a restart), the app restores from this URL before seeding.
CHAIN_SNAPSHOT_URL = os.environ.get("CHAIN_SNAPSHOT_URL") or None
