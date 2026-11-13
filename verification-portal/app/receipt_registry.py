"""Server-side receipt registry (employer pack, extras round 6).

Every verification (document or hash) produces a short, immutable receipt
record: receipt ID -> hash, verdict, timestamp, endpoint. An employer can then
check "was this receipt issued by us?" via GET /api/receipt/{id} without
re-verifying. Records are append-only ring-buffered to RECEIPT_REGISTRY_CAP so
the free tier never grows without bound. Receipt IDs are also embedded in the
downloadable HTML receipt (client falls back to its own ID only when the server
one is missing).
"""

import json
import os
import secrets
import threading
import time

from . import config as cfg

_RECEIPTS_FILE = cfg.BASE_DIR / "data" / "receipts.json"
_lock = threading.Lock()


def _load() -> list:
    try:
        with open(_RECEIPTS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(records: list) -> None:
    _RECEIPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _RECEIPTS_FILE.with_name(_RECEIPTS_FILE.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False)
    os.replace(tmp, _RECEIPTS_FILE)


def register(hashed_document: str, verdict: str, verified_at: float,
             endpoint: str) -> str:
    """Record one verification and return its receipt ID."""
    rid = f"RCP-{int(verified_at):x}-{secrets.token_hex(2).upper()}"
    with _lock:
        records = _load()
        records.append({
            "receipt_id": rid,
            "hashed_document": hashed_document,
            "verdict": verdict,
            "verified_at": verified_at,
            "endpoint": endpoint,
        })
        cap = cfg.RECEIPT_REGISTRY_CAP
        if len(records) > cap:
            records = records[-cap:]
        _save(records)
    return rid


def get(receipt_id: str):
    with _lock:
        for rec in _load():
            if rec.get("receipt_id") == receipt_id:
                return rec
        return None
