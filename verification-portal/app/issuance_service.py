"""issuance_service.py — issuing and revoking credentials (internal, U1.2).

Depends on :mod:`chain_core` for the chain lock and signer loading.
"""

import time

from . import blockchain_util, repository
from .chain_core import _load_signer, _lock, _store_raw_document, ensure_chain
from .config import CHAIN_DIR, REVOCATION_REASON_MAXLEN

# U15: revoked_records() walks every block, and four call sites (single verify,
# document verify, batch verify of up to 500 hashes, PDF rendering) ask for it.
# A batch of 500 would otherwise walk the chain 500 times. The cache is keyed on
# the chain height, so any new block — including the REVOKE that just landed —
# invalidates it immediately; the TTL only bounds repeated scans when nothing
# changes.
_REVOKED_TTL = 5.0
_revoked_cache: tuple[float, int, list] | None = None


def hash_of(document: dict) -> str:
    """On-chain hash of a full credential document."""
    return blockchain_util.issue_payload(document)["HashedDocument"]


def issue(document: dict) -> dict:
    ensure_chain()
    algo, priv = _load_signer()
    payload = blockchain_util.issue_payload(document)  # ValueError if sections missing
    with _lock:
        block = blockchain_util.append_block(str(CHAIN_DIR), payload, [(algo, priv)])
        _store_raw_document(document, payload["HashedDocument"])
    return {
        "hashed_document": payload["HashedDocument"],
        "height": block["height"],
        "block": block,
    }


def revoke(hashed_document: str, reason: str | None = None,
           effective_at: float | None = None) -> dict:
    ensure_chain()
    algo, priv = _load_signer()
    payload = blockchain_util.revoke_payload(hashed_document)
    if reason:
        payload["reason"] = str(reason)[:REVOCATION_REASON_MAXLEN]
    if effective_at is not None:
        payload["effective_at"] = float(effective_at)
    with _lock:
        block = blockchain_util.append_block(str(CHAIN_DIR), payload, [(algo, priv)])
        # Write-through revocation cache. The chain stays authoritative: every
        # verdict still reads revoked_records(), so a missing index row can slow
        # a lookup down but can never flip a VERDICT.
        repository.store("revocation_index").upsert(
            hashed_document, block["height"], True,
            payload.get("reason"), payload.get("effective_at"))
    return {
        "hashed_document": hashed_document,
        "height": block["height"],
        "block": block,
    }


def revoked_records() -> list:
    """Per-hash latest REVOKE record (hash, height, reason, effective_at),
    sorted by hash — the source for the signed status list."""
    global _revoked_cache
    ensure_chain()
    chain = str(CHAIN_DIR)
    height = blockchain_util.last_height(chain)
    now = time.time()
    if (_revoked_cache is not None and _revoked_cache[1] == height
            and now - _revoked_cache[0] < _REVOKED_TTL):
        return list(_revoked_cache[2])
    latest = {}
    for h in range(1, height + 1):
        try:
            block = blockchain_util.load_block(chain, h)
        except blockchain_util.ChainDataError:
            continue
        payload = block.get("payload") or {}
        if payload.get("action") != "REVOKE":
            continue
        doc_hash = payload.get("HashedDocument")
        if doc_hash:
            latest[doc_hash] = {
                "hash": doc_hash,
                "height": h,
                "reason": payload.get("reason"),
                "effective_at": payload.get("effective_at"),
            }
    rows = sorted(latest.values(), key=lambda r: r["hash"])
    _revoked_cache = (now, height, rows)
    return list(rows)


def revoke_meta(hashed_document: str) -> dict:
    """Latest REVOKE metadata for one hash (reason / effective_at), if any."""
    for rec in revoked_records():
        if rec["hash"] == hashed_document:
            return rec
    return {}


def rebuild_revocation_index() -> int:
    """Replay every REVOKE block into the index; returns rows touched.

    Recovery path for a deleted/lost index (it is a cache, not a fact source).
    Not called at startup on purpose: verification reads the chain, so an empty
    index costs a scan but never a wrong answer, and booting stays cheap.
    """
    rows = revoked_records()
    store = repository.store("revocation_index")
    for rec in rows:
        store.upsert(rec["hash"], rec.get("height"), True,
                     rec.get("reason"), rec.get("effective_at"))
    return len(rows)
