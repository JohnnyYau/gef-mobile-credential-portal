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

# Free-tier persistence (extras round 7): CHAIN_SNAPSHOT_URL points at a
# backup_chain.py export. When the chain dir is empty at boot (ephemeral
# storage after a restart), the app restores from this URL before seeding.
CHAIN_SNAPSHOT_URL = os.environ.get("CHAIN_SNAPSHOT_URL") or None
