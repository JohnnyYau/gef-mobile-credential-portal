"""notifier.py — email notifications (post-Week-3 extra G; worker-ised U12 R4).

Pluggable: with SMTP_* env vars set, real emails are sent over SMTP+TLS; by
default (sandbox has no mail server) it runs in dry-run mode and records the
would-be message to ``<chain-dir>/../notifications.jsonl`` so the feature is
still demoable and testable end to end.

U12 R4 changes the shape of the feature in three ways, all of them about who
decides where mail goes:

* **The recipient is configuration.** ``NOTIFY_TO`` is the deployment's own
  inbox. ``notify_issue()`` still accepts the old ``to`` argument — callers
  keep their signature — but the value is ignored, so a request body can no
  longer turn the portal into a relay.
* **Requests enqueue, a worker sends.** The issuing request never blocks on
  SMTP and never dials out; a daemon thread started by the app lifespan drains
  the queue.
* **Duplicates and bursts are bounded.** One notification per
  ``hashed_document``, and at most ``NOTIFY_PER_HOUR`` attempts per hour.

``drain()`` is synchronous and public so tests (and a shutdown flush) can run
the queue without a thread.
"""

import logging
import queue
import smtplib
import threading
import time
from email.message import EmailMessage
from pathlib import Path

from . import repository
from .config import (
    CHAIN_DIR,
    EMAIL_ENABLED,
    EMAIL_FROM,
    NOTIFICATION_RECENT_LIMIT,
    NOTIFY_PER_HOUR,
    NOTIFY_TO,
    PUBLIC_BASE_URL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_TIMEOUT,
    SMTP_USER,
)

logger = logging.getLogger("notifications")

_lock = threading.Lock()
_queue: "queue.Queue[tuple[str, str]]" = queue.Queue(maxsize=1000)
_seen: set[str] = set()
_hour_window = [0.0]
_hour_count = [0]
_worker: threading.Thread | None = None
_stop = threading.Event()


def _log_path() -> Path:
    return CHAIN_DIR.parent / "notifications.jsonl"


def _recipient() -> str | None:
    value = (NOTIFY_TO or "").strip()
    return value or None


def _record(to, subject, status, detail, url=None):
    # Same record shape as before; the store picks jsonl or a SQLite table.
    return repository.store("notifications").record(
        to, subject, status, detail, url)


def _send_smtp(to, subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM or SMTP_USER
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
        server.starttls()
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASSWORD or "")
        server.send_message(msg)


def _message(hashed_document: str, doc_type: str) -> tuple[str, str, str]:
    url = f"{PUBLIC_BASE_URL}/verify?hash={hashed_document}"
    subject = f"Your {doc_type} is on the chain"
    body = (
        f"Your {doc_type} was issued on the Gef26 private credential chain.\n\n"
        f"On-chain hash: {hashed_document}\n"
        f"Verify it here: {url}\n\n"
        "The verification portal checks integrity, signer trust, on-chain "
        "record, hash match, signature and revocation status."
    )
    return subject, body, url


def enqueue_issue(hashed_document: str, doc_type: str,
                  request_email: str | None = None) -> dict:
    """Queue one notification; returns the status the caller may report."""
    with _lock:
        if hashed_document in _seen:
            return {"status": "duplicate", "to": _recipient(),
                    "detail": "this credential was already notified"}
        _seen.add(hashed_document)
    detail = "awaiting worker"
    if request_email and str(request_email).strip():
        detail += "; caller-supplied address ignored"
    try:
        _queue.put_nowait((str(hashed_document), str(doc_type)))
    except queue.Full:
        return {"status": "dropped", "to": _recipient(),
                "detail": "notification queue is full"}
    return {"status": "queued", "to": _recipient(), "detail": detail}


def _hour_allows() -> bool:
    now = time.monotonic()
    if now - _hour_window[0] >= 3600:
        _hour_window[0] = now
        _hour_count[0] = 0
    if _hour_count[0] >= NOTIFY_PER_HOUR:
        return False
    _hour_count[0] += 1
    return True


def _deliver(hashed_document: str, doc_type: str) -> dict:
    subject, body, url = _message(hashed_document, doc_type)
    to = _recipient()
    if not to:
        return _record(None, subject, "logged",
                       "no NOTIFY_TO configured — event recorded, nothing sent",
                       url)
    if EMAIL_ENABLED and SMTP_HOST:
        try:
            _send_smtp(to, subject, body)
            return _record(to, subject, "sent", "via SMTP", url)
        except (OSError, ValueError, TypeError, smtplib.SMTPException) as exc:
            return _record(to, subject, "error", str(exc), url)
    return _record(to, subject, "dry-run",
                   f"EMAIL_ENABLED/SMTP not configured — would send {url}", url)


def drain(max_items: int = 50) -> int:
    """Deliver queued notifications now. Returns how many were consumed."""
    handled = 0
    for _ in range(max_items):
        try:
            hashed, doc_type = _queue.get_nowait()
        except queue.Empty:
            break
        handled += 1
        if not _hour_allows():
            subject, _body, url = _message(hashed, doc_type)
            _record(None, subject, "throttled",
                    f"NOTIFY_PER_HOUR={NOTIFY_PER_HOUR} reached", url)
            continue
        try:
            _deliver(hashed, doc_type)
        except Exception:  # noqa: BLE001 — one bad message must not stop the loop
            logger.exception("notification delivery failed for %s", hashed[:12])
    return handled


def start_worker(interval: float = 1.0) -> None:
    """Start the daemon draining thread (idempotent)."""
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    _stop.clear()

    def loop():
        while not _stop.is_set():
            try:
                drain()
            except Exception:  # noqa: BLE001 — keep the thread alive
                logger.exception("notification worker iteration failed")
            _stop.wait(interval)

    _worker = threading.Thread(target=loop, name="notification-worker",
                               daemon=True)
    _worker.start()


def stop_worker(flush: bool = True) -> None:
    """Stop the thread, then deliver whatever is still queued."""
    _stop.set()
    global _worker
    if _worker is not None:
        _worker.join(timeout=2.0)
        _worker = None
    if flush:
        try:
            drain()
        except Exception:  # noqa: BLE001 — shutdown must not raise
            logger.exception("final notification flush failed")


def notify_issue(to: str | None, hashed_document: str, doc_type: str) -> dict:
    """Compatibility entry point.

    ``to`` is kept in the signature because callers and tests already pass it,
    and deliberately ignored: the address comes from ``NOTIFY_TO``.
    """
    return enqueue_issue(hashed_document, doc_type, request_email=to)


def recent_notifications(limit=NOTIFICATION_RECENT_LIMIT) -> list:
    """Last notifications (for the demo Log tab / tests)."""
    return repository.store("notifications").recent(limit)
