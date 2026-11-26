"""signer_service.py — multi-signer management (internal, batch U1.2).

Registration, activation and signing. Key material and the chain lock live in
:mod:`chain_core`, which this module depends on (never the other way round).
"""

import json

from . import blockchain_util, crypto_util
from .chain_core import (
    _active_signer_fgpt,
    _load_signer,
    _passphrase,
    _signer_priv_path,
    ensure_chain,
)
from .config import CHAIN_DIR
from .errors import ValidationError


def sign_payload(payload: dict):
    """Sign an arbitrary payload with the active signer.

    Returns ``(ds_algo, signature_b64)`` only — the nonce is **not** returned,
    so anything signed through this cannot be verified by a third party. Use
    :func:`sign_payload_envelope` when the signature must travel with what is
    needed to check it. (The old docstring claimed the nonce was embedded in the
    payload; it never was, which made the status list's signature unverifiable
    until U17.)
    """
    algo, priv = _load_signer()
    _, signature = crypto_util.sign_json(payload, algo, priv)
    return algo, signature


def sign_payload_envelope(payload: dict) -> dict:
    """Sign a payload and return everything a third party needs to check it.

    U17: :func:`sign_payload` returns ``(algo, signature)`` only, and its
    docstring claims the nonce is embedded in the payload — it is not. The
    status list was built through it, so its signature could never be verified,
    by us or by the employer who cached it. This returns the nonce, and the
    signer's real name/fingerprint taken from the key that signed rather than
    from ``SIGNER_NAME`` in config (which keeps naming the first signer after a
    rotation).
    """
    ensure_chain()
    algo, priv = _load_signer()
    nonce, signature = crypto_util.sign_json(payload, algo, priv)
    _, sha256 = crypto_util.getfgpt(priv.public_key())
    name = next((s.get("name") for s in blockchain_util.trusted_signers(str(CHAIN_DIR))
                 if s.get("sha256fgpt") == sha256), None)
    return {"algo": algo, "signer": name, "sha256fgpt": sha256,
            "nonce": nonce, "value": signature}


def public_keys() -> dict:
    """Registered signers with their public key in PEM — the offline anchor.

    U17: ``GET /api/statuslist`` says an employer can cache the list and answer
    "is this revoked?" offline. Without a public key that promise is empty: the
    list carries a signature the reader has no way to check. This is the other
    half — the key material, fingerprints and retirement boundaries, so a
    verifier that never talks to this portal can still check the signature.
    """
    ensure_chain()
    signers = blockchain_util.trusted_signers(str(CHAIN_DIR))
    out = []
    for s in signers:
        path = blockchain_util._signer_pub_path(str(CHAIN_DIR), s["sha256fgpt"])
        try:
            with open(path, "r", encoding="utf-8") as fh:
                pem = fh.read()
        except OSError:
            pem = None
        out.append({
            "name": s.get("name"),
            "ds_algo": s.get("ds_algo"),
            "sha1fgpt": s.get("sha1fgpt"),
            "sha256fgpt": s.get("sha256fgpt"),
            "retired_at_height": s.get("retired_at_height"),
            "pubkey_pem": pem,
        })
    return {"signers": out}


def _effective_active(signers: list) -> str | None:
    """The signer that would actually issue — with the same fallback the UI sees.

    ``active-signer.json`` is only written when someone switches signers, so a
    freshly seeded chain has no such file and ``_active_signer_fgpt`` returns
    None. :func:`list_signers` has always fallen back to the first registered
    signer (that is what the Signers tab shows as active); retiring has to use
    the same answer, or the chain's *de facto* active key looks retirable.
    """
    active = _active_signer_fgpt()
    if active is None and signers:
        active = signers[0]["sha256fgpt"]
    return active


def list_signers() -> dict:
    """Registered signers + which one currently issues."""
    ensure_chain()
    signers = blockchain_util.trusted_signers(str(CHAIN_DIR))
    return {"signers": signers, "active": _effective_active(signers)}


def add_signer(name: str, ds_algo: str) -> dict:
    """Generate a fresh signer key, register it, and return its record."""
    ensure_chain()
    try:
        priv, pub = crypto_util.gen_dskey(ds_algo)
    except ValueError as exc:  # bad algo name surfaces as 422
        raise ValidationError(f"Unsupported ds_algo '{ds_algo}': {exc}") from exc
    _, sha256 = crypto_util.getfgpt(pub)
    key_dir = CHAIN_DIR / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    crypto_util.save_privkey(priv, ds_algo, str(_signer_priv_path(sha256)),
                             _passphrase() or None)
    blockchain_util.register_signer(str(CHAIN_DIR), name, pub, ds_algo)
    record = next(s for s in blockchain_util.trusted_signers(str(CHAIN_DIR))
                  if s["sha256fgpt"] == sha256)
    record["active"] = (sha256 == _active_signer_fgpt())
    return record


def set_active_signer(sha256fgpt: str) -> dict:
    """Make the given registered signer the one that signs new blocks."""
    ensure_chain()
    signers = blockchain_util.trusted_signers(str(CHAIN_DIR))
    match = [s for s in signers if s["sha256fgpt"] == sha256fgpt]
    if not match:
        raise ValueError("No registered signer has that fingerprint.")
    if match[0].get("retired_at_height") is not None:
        raise ValueError(
            f"That signer is retired as of block #{match[0]['retired_at_height']}; "
            f"pick another, or re-register its key to trust it again.")
    path = CHAIN_DIR / "active-signer.json"
    path.write_text(json.dumps({"sha256fgpt": sha256fgpt}), encoding="utf-8")
    return {"active": sha256fgpt}


def retire_signer(sha256fgpt: str) -> dict:
    """Stop trusting *new* blocks from a signer without deleting its history.

    U16: the reason this exists is a real failure. A signer was registered, used
    for a block, and then dropped from ``info.yaml`` — which made that block
    unverifiable and turned every verdict on the chain into INVALID. Retiring
    keeps the key and adds a height boundary instead, so what was signed before
    retirement still verifies and nothing signed after it does.
    """
    ensure_chain()
    signers = blockchain_util.trusted_signers(str(CHAIN_DIR))
    if not any(s["sha256fgpt"] == sha256fgpt for s in signers):
        raise ValueError("No registered signer has that fingerprint.")
    if _effective_active(signers) == sha256fgpt:
        raise ValidationError(
            "This signer is active: switch to another signer first. Retiring the "
            "active key would make its next block untrusted and break the chain.")
    return blockchain_util.retire_signer(str(CHAIN_DIR), sha256fgpt)


def snapshot_manifest() -> dict:
    """Signed summary of the chain's current state (batch U4.3).

    Answers "what exactly was this chain when you looked at it": identity,
    height, tip hash, hash algorithm, parameter/schema versions and the signer
    set. Signed by the active signer, so a party that trusts that signer can
    compare a snapshot taken elsewhere without re-reading every block.
    """
    ensure_chain()
    params = blockchain_util.chain_params(str(CHAIN_DIR))
    height = params["last_block_height"]
    tip = blockchain_util.load_block(str(CHAIN_DIR), height)
    manifest = {
        "chain_id": params["chain_id"],
        "chain_name": params["chain_name"],
        "height": height,
        "last_block_hash": crypto_util.hash_json(tip,
                                                 params["content_hash_algo"]),
        "content_hash_algo": params["content_hash_algo"],
        "params_version": params["params_version"],
        "schema_version": blockchain_util.BLOCK_SCHEMA_VERSION,
        "signers": [
            {"name": s.get("name"), "sha256fgpt": s.get("sha256fgpt"),
             "ds_algo": s.get("ds_algo")}
            for s in params["trusted_signers"]
        ],
    }
    algo, priv = _load_signer()
    nonce, signature = crypto_util.sign_json(manifest, algo, priv)
    _, sha256 = crypto_util.getfgpt(priv.public_key())
    return {
        "manifest": manifest,
        "signature": {"DSAlgo": algo, "DSsha256fgpt": sha256,
                      "DSnonce": nonce, "DSignature": signature},
    }
