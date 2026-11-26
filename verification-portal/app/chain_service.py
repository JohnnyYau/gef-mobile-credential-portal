"""chain_service.py — service-layer facade (thin re-export, batch U1.2).

The implementation moved into four internal modules so each has a single
responsibility:

    chain_core.py         chain lock, paths, signer loading, init/seed/restore
    signer_service.py     multi-signer registration, activation, signing
    issuance_service.py   issuing and revoking credentials
    query_service.py      status, six-check verification, tail, student lookup

This module keeps every previously public name importable from
``app.chain_service`` so callers (main.py, custom_service, chat_service,
person_context, statuslist, scripts, tests) need no change at all.

Dependency direction is one-way — facade → services → chain_core → chain core
libraries — so there is no import cycle.
"""

from .chain_core import (  # noqa: F401 — re-exported for backward compatibility  # noqa: F401
    SAMPLE_DIPLOMA,
    SAMPLE_REVOKED_DOC,
    SAMPLE_TRANSCRIPT,
    _lock,
    chain_info,
    ensure_chain,
    ensure_revoked_sample,
    restore_snapshot_if_needed,
)
from .config import CHAIN_DIR  # noqa: F401 — callers/tests import it from here
from .issuance_service import (  # noqa: F401
    hash_of,
    issue,
    revoke,
    revoke_meta,
    revoked_records,
)
from .query_service import (  # noqa: F401
    _corrupt_verdict,
    chain_snapshot_id,
    chain_tail,
    demo_credentials,
    on_chain_payload,
    status,
    student_credentials,
    verify_document,
    verify_hash,
)
from .signer_service import (  # noqa: F401
    add_signer,
    list_signers,
    public_keys,
    retire_signer,
    set_active_signer,
    sign_payload,
    sign_payload_envelope,
    snapshot_manifest,
)

__all__ = [
    "CHAIN_DIR",
    "SAMPLE_DIPLOMA",
    "SAMPLE_REVOKED_DOC",
    "SAMPLE_TRANSCRIPT",
    "add_signer",
    "chain_info",
    "chain_snapshot_id",
    "chain_tail",
    "demo_credentials",
    "ensure_chain",
    "ensure_revoked_sample",
    "hash_of",
    "issue",
    "list_signers",
    "on_chain_payload",
    "public_keys",
    "restore_snapshot_if_needed",
    "retire_signer",
    "revoke",
    "revoke_meta",
    "revoked_records",
    "set_active_signer",
    "sign_payload",
    "sign_payload_envelope",
    "snapshot_manifest",
    "status",
    "student_credentials",
    "verify_document",
    "verify_hash",
]
