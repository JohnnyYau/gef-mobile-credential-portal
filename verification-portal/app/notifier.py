"""notifier.py — email notifications (post-Week-3 extra G).

Pluggable: with SMTP_* env vars set, real emails are sent over SMTP+TLS; by
default (sandbox has no mail server) it runs in dry-run mode and records the
would-be message to ``<chain-dir>/../notifications.jsonl`` so the feature is
still demoable and testable end to end.
"""

import json
import smtplib
import threading
import time
from email.message import EmailMessage
from pathlib import Path

from .config import (
    CHAIN_DIR,
    EMAIL_ENABLED,
    EMAIL_FROM,
    PUBLIC_BASE_URL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
)

_lock = threading.Lock()


def _log_path() -> Path:
    return CHAIN_DIR.parent / "notifications.jsonl"


def _record(to, subject, status, detail, url=None):
    rec = {
        "time": int(time.time()),
        "to": to,
        "subject": subject,
        "status": status,
        "detail": detail,
    }
    if url:
        rec["url"] = url
    try:
        with open(_log_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return rec


def _send_smtp(to, subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM or SMTP_USER
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.starttls()
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASSWORD or "")
        server.send_message(msg)


def notify_issue(to: str | None, hashed_document: str, doc_type: str):
    """Send (or dry-run) a "your credential is on the chain" message."""
    if not to or not str(to).strip():
        return {"status": "skipped", "to": None, "detail": "no email provided"}
    to = str(to).strip()
    url = f"{PUBLIC_BASE_URL}/verify?hash={hashed_document}"
    subject = f"Your {doc_type} is on the chain"
    body = (
        f"Your {doc_type} was issued on the Gef26 private credential chain.\n\n"
        f"On-chain hash: {hashed_document}\n"
        f"Verify it here: {url}\n\n"
        "The verification portal checks integrity, signer trust, on-chain "
        "record, hash match, signature and revocation status."
    )
    with _lock:
        if EMAIL_ENABLED and SMTP_HOST:
            try:
                _send_smtp(to, subject, body)
                return _record(to, subject, "sent", "via SMTP", url)
            except Exception as exc:  # noqa: BLE001 — surface any SMTP failure
                return _record(to, subject, "error", str(exc), url)
        return _record(to, subject, "dry-run",
                       f"EMAIL_ENABLED/SMTP not configured — would send {url}",
                       url)


def recent_notifications(limit=10) -> list:
    """Last notifications from the jsonl (for the demo Log tab / tests)."""
    out = []
    try:
        path = _log_path()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out
