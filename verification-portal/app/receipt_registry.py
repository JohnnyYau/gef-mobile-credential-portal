"""Server-side receipt registry (employer pack, extras round 6).

Every verification (document or hash) produces a short, immutable receipt
record: receipt ID -> hash, verdict, timestamp, endpoint. An employer can then
check "was this receipt issued by us?" via GET /api/receipt/{id} without
re-verifying. Records are append-only ring-buffered to RECEIPT_REGISTRY_CAP so
the free tier never grows without bound. Receipt IDs are also embedded in the
downloadable HTML receipt (client falls back to its own ID only when the server
one is missing).

Since batch U2 this module is a thin facade over ``repository``; the ring
buffer is enforced inside the store implementation.
"""

from . import repository


def register(hashed_document: str, verdict: str, verified_at: float,
             endpoint: str) -> str:
    """Record one verification and return its receipt ID."""
    return repository.store("receipts").register(
        hashed_document, verdict, verified_at, endpoint)


def get(receipt_id: str):
    return repository.store("receipts").get(receipt_id)
