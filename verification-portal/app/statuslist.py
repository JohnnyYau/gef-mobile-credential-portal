"""Signed revocation status list (OCSP-like) — employer pack, extras round 6.

GET /api/statuslist returns a signed, cacheable snapshot of every revoked
credential on the chain: {hash, reason, effective_at} + chain snapshot +
signature by the active signer. An employer can cache it (ETag / max-age) and
answer "is this credential revoked?" offline until the next refresh — the same
trust model as a certificate status list. It is rebuilt only when the chain
changes (snapshot id), so it is cheap under load.

U17: the v1 signature carried only ``algo``, ``value`` and a ``signer`` name
lifted from ``SIGNER_NAME`` in config — no nonce, no fingerprint, no public
key. The nonce is required to recompute the signed message, so that signature
was unverifiable by anyone, which quietly falsified the "offline" promise above.
v2 signs with :func:`chain_service.sign_payload_envelope`: the nonce, the real
signing key's fingerprint, and its registry name all travel with the value, and
``GET /api/signers/keys`` publishes the matching public keys.
"""

import threading
import time

from . import chain_service
from . import config as cfg
from .crypto_util import hash_json

SCHEMA = "gef26.statuslist.v2"

_cache = {"etag": None, "payload": None, "snapshot_id": None}
_lock = threading.Lock()


def build(force: bool = False):
    """Return (payload_dict, etag). Rebuilds only when the chain changed."""
    with _lock:
        snap = chain_service.chain_snapshot_id()
        if not force and _cache["payload"] and _cache["snapshot_id"] == snap:
            return _cache["payload"], _cache["etag"]

        revoked = chain_service.revoked_records()
        if len(revoked) > cfg.STATUSLIST_MAX_ENTRIES:
            revoked = revoked[:cfg.STATUSLIST_MAX_ENTRIES]

        height_s, _, last_hash = snap.partition(":")
        payload = {
            "schema": SCHEMA,
            "generated_at": int(time.time()),
            "snapshot": {
                "chain_name": cfg.CHAIN_NAME,
                "height": int(height_s),
                "last_block_hash": last_hash,
                "content_hash_algo": "sha3_512",
            },
            "counts": {"revoked": len(revoked)},
            "revoked": revoked,
        }
        payload["signature"] = chain_service.sign_payload_envelope(payload)
        etag = '"' + hash_json(payload)[:32] + '"'
        _cache.update(etag=etag, payload=payload, snapshot_id=snap)
        return payload, etag
