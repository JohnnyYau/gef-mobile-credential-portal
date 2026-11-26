"""blockchain-util.py — private credential chain: blocks, chain, verification.

Storage layout (per TODO.md / JSONSTRUCTURE.md)
------------------------------------------------
<chain_name>/
    info.yaml                 # chain metadata + trusted data-signer registry
    blocks/
        block-000000000.json  # genesis block (height 0)
        block-000000001.json  # written via .temp then renamed (atomic)
    rawjsondocs/
        <HashedDocument>.json # optional: the original document under its hash

API (per TODO.md)
-----------------
init_block(chain_addr, ...)      create chain directory + genesis block
register_signer(...)             add a trusted data signer (by SPKI fingerprint)
append_block(chain_addr, payload, signers)   append + update info.yaml
fetch_block(chain_addr, height)  return the block JSON
verify_block(chain_addr, height) verify signatures + hash links
verify_chain(chain_addr)         verify whole chain from genesis
fetch_status(chain_addr, HashedDocument)  -> revoked? / valid?
verify_document(chain_addr, document)     verifier's 6 checks + verdict

Block payload (ISSUE / REVOKE) carries only hashes — never raw personal data.
"""

import copy
import json
import os
import re
import threading
import time
from typing import Any

import yaml

try:
    from . import config as cfg  # packaged inside app/
except ImportError:  # pragma: no cover — run from the repo root / notebooks
    class _Cfg:  # minimal fallback so standalone scripts still work
        CHAIN_INTEGRITY_TTL = float(os.environ.get("CHAIN_INTEGRITY_TTL", "5"))
        CHAIN_INDEX_TTL = float(os.environ.get("CHAIN_INDEX_TTL", "30"))

    cfg = _Cfg()  # type: ignore[assignment]

try:
    from . import crypto_util  # packaged inside app/
except ImportError:  # pragma: no cover — run from the repo root / notebooks
    import crypto_util  # type: ignore[no-redef]

BLOCK_FILE_RE = re.compile(r"^block-(\d{9})\.json$")

# --------------------------------------------------------------------------
# Read caches (batch U9-A)
#
# Everything here is keyed on a *fingerprint* of what is on disk, not on an
# assumption about who calls whom: `_chain_fingerprint()` is (height, count,
# summed size, newest mtime) over the block directory, so any append, rewrite
# or truncation changes it and the cached value is dropped. The TTL on top
# bounds the one case the fingerprint cannot see — an edit that preserves
# every file's size and mtime — to a few seconds of staleness instead of
# forever. Verdict-carrying checks therefore never go stale by construction;
# this is the same reasoning that makes the read-side cache safe to put in
# front of `verify_chain()`.
# --------------------------------------------------------------------------

_CACHE_LOCK = threading.Lock()
_INFO_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_CHAIN_CACHE: dict[str, tuple[tuple, float, bool, list[dict[str, Any]]]] = {}
_INDEX_CACHE: dict[str, tuple[tuple, float, dict[str, dict[str, list[int]]]]] = {}


def _block_dir(chain_addr: str) -> str:
    return os.path.join(chain_addr, "blocks")


def _chain_fingerprint(chain_addr: str) -> tuple:
    """Cheap identity of the block directory: (count, total size, newest mtime)."""
    count = 0
    total = 0
    newest = 0
    try:
        entries = os.scandir(_block_dir(chain_addr))
    except OSError:
        return (0, 0, 0)
    with entries:
        for entry in entries:
            if not entry.name.endswith(".json"):
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            count += 1
            total += stat.st_size
            newest = max(newest, stat.st_mtime_ns)
    return (count, total, newest)


def invalidate_caches(chain_addr: str | None = None) -> None:
    """Drop read caches for one chain (or all) — used by tests and tooling."""
    with _CACHE_LOCK:
        if chain_addr is None:
            _INFO_CACHE.clear()
            _CHAIN_CACHE.clear()
            _INDEX_CACHE.clear()
            return
        _INFO_CACHE.pop(_info_path(chain_addr), None)
        _CHAIN_CACHE.pop(chain_addr, None)
        _INDEX_CACHE.pop(chain_addr, None)


# --------------------------------------------------------------------------
# info.yaml (chain metadata + trusted signers)
# --------------------------------------------------------------------------


def _info_path(chain_addr: str) -> str:
    return os.path.join(chain_addr, "info.yaml")


class ChainDataError(RuntimeError):
    """Raised when a chain file is missing, unreadable or corrupted."""


# Signature-record scheme id (batch U4.1). v1 = nonce-wrapped HMAC over the
# payload hash. Blocks written before this field existed carry no DSscheme and
# are read as v1 implicitly, so old chains never need rewriting.
SIGNATURE_SCHEME = "hmac-nonce-wrap-v1"

# Block schema version (batch U4.3). 1 = pre-U4.1 record (no DSscheme), 2 = the
# explicit signature record. Only written into new blocks; absent means 1.
BLOCK_SCHEMA_VERSION = 2
PARAMS_VERSION = 1


def chain_params(chain_addr: str) -> dict[str, Any]:
    """Chain identity and parameters, with defaults for pre-U4.3 chains.

    Older ``info.yaml`` files carry only name/algo/height/signers. Rather than
    rewriting them (which would touch a live chain's metadata), missing values
    are derived on read: ``chain_id`` from the name+algo pair, versions as 1.
    """
    info = read_info(chain_addr)
    algo = info.get("content_hash_algo", "sha3_512")
    name = info.get("chain_name", "")
    chain_id = info.get("chain_id") or (
        "cid-" + crypto_util.hash_json({"chain_name": name, "algo": algo},
                                       algo)[:24])
    return {
        "chain_id": chain_id,
        "chain_name": name,
        "content_hash_algo": algo,
        "last_block_height": int(info.get("last_block_height", 0)),
        "params_version": int(info.get("params_version", 1)),
        "schema_version": int(info.get("schema_version", 1)),
        "trusted_signers": info.get("trusted_signers", []),
    }


def read_info(chain_addr: str) -> dict[str, Any]:
    """Parse info.yaml, memoised on (size, mtime_ns).

    U9-A: a single `verify_document()` used to parse this YAML **15 times**
    (registry lookups, signature verification, params, height). Writing info
    goes through `write_info`'s atomic replace, which changes the mtime, so the
    cache invalidates itself without any explicit invalidation call. A copy is
    returned because callers mutate the dict they get back (`register_signer`).
    """
    path = _info_path(chain_addr)
    try:
        stat = os.stat(path)
    except OSError as exc:
        raise ChainDataError(f"info.yaml is missing or corrupted: {exc}") from exc
    signature = (stat.st_size, stat.st_mtime_ns)
    with _CACHE_LOCK:
        cached = _INFO_CACHE.get(path)
    if cached is not None and cached[0] == signature:
        return copy.deepcopy(cached[1])
    try:
        with open(path, encoding="utf-8") as fh:
            info = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ChainDataError(f"info.yaml is missing or corrupted: {exc}") from exc
    with _CACHE_LOCK:
        _INFO_CACHE[path] = (signature, info)
    return copy.deepcopy(info)


def write_info(chain_addr: str, info: dict[str, Any]) -> None:
    """Atomic write: .temp then rename (portal hardening)."""
    final_path = _info_path(chain_addr)
    temp_path = final_path + ".temp"
    with open(temp_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(info, fh, allow_unicode=True, sort_keys=False)
    os.replace(temp_path, final_path)


# --------------------------------------------------------------------------
# Chain initialisation
# --------------------------------------------------------------------------


def init_block(chain_addr: str, chain_name: str = "Gef26-credential-chain",
               content_hash_algo: str = "sha3_512",
               overwrite: bool = False) -> dict[str, Any]:
    """Create a chain directory and a deterministic genesis block (height 0).

    The genesis block has a blank ``prevHashSum`` (per JSONSTRUCTURE.md) and a
    fixed timestamp 0 so the same chain name always starts from the same root.
    """
    if os.path.exists(_info_path(chain_addr)) and not overwrite:
        raise FileExistsError(
            f"Chain already initialised at {chain_addr} (use overwrite=True to reset)."
        )

    os.makedirs(os.path.join(chain_addr, "blocks"), exist_ok=True)
    os.makedirs(os.path.join(chain_addr, "rawjsondocs"), exist_ok=True)

    genesis = {
        "height": 0,
        "contentHashAlgo": content_hash_algo,
        "prevHashSum": "",
        "timestamp": 0,
        "schemaVersion": BLOCK_SCHEMA_VERSION,
        "payload": {
            "action": "GENESIS",
            "chain_name": chain_name,
            "note": "Deterministic genesis block",
        },
        "DataSignatureInfo": [],
    }

    chain_id = "cid-" + crypto_util.hash_json(
        {"chain_name": chain_name, "algo": content_hash_algo},
        content_hash_algo)[:24]
    write_info(chain_addr, {
        "chain_name": chain_name,
        "chain_id": chain_id,
        "content_hash_algo": content_hash_algo,
        "params_version": PARAMS_VERSION,
        "schema_version": BLOCK_SCHEMA_VERSION,
        "last_block_height": 0,
        "trusted_signers": [],
    })
    _write_block_file(chain_addr, genesis)
    return genesis


# --------------------------------------------------------------------------
# Trusted signer registry (the chain's "issuer registry")
# --------------------------------------------------------------------------


def register_signer(chain_addr: str, name: str, pub_key: Any,
                    ds_algo: str) -> str:
    """Register a trusted data signer by its SPKI fingerprint.

    The public key is persisted under ``<chain>/keys/signer-<fgpt12>.pem`` so
    later verification can re-load it by fingerprint alone.
    """
    sha1fgpt, sha256fgpt = crypto_util.getfgpt(pub_key)
    info = read_info(chain_addr)
    signers = [s for s in info.get("trusted_signers", [])
               if s.get("sha256fgpt") != sha256fgpt]
    signers.append({
        "name": name,
        "ds_algo": ds_algo,
        "sha1fgpt": sha1fgpt,
        "sha256fgpt": sha256fgpt,
    })
    info["trusted_signers"] = signers
    write_info(chain_addr, info)

    key_dir = os.path.join(chain_addr, "keys")
    os.makedirs(key_dir, exist_ok=True)
    crypto_util.save_pubkey(pub_key, ds_algo, _signer_pub_path(chain_addr, sha256fgpt))
    return sha256fgpt


def trusted_signers(chain_addr: str) -> list[dict[str, Any]]:
    """Return the trusted-signer list [{name, ds_algo, sha1fgpt, sha256fgpt}]."""
    return read_info(chain_addr).get("trusted_signers", [])


def is_trusted(chain_addr: str, sha256fgpt: str) -> bool:
    """True if the given SPKI fingerprint is a registered signer."""
    return any(s.get("sha256fgpt") == sha256fgpt
               for s in trusted_signers(chain_addr))


def signer_trusted_at(chain_addr: str, sha256fgpt: str, height: int) -> bool:
    """Was this signer trusted when the block at ``height`` was written?

    U16: retiring a signer must not retroactively invalidate the blocks it
    signed *before* retirement. That is the whole difference between "we
    stopped trusting this key" and "the chain is broken": the first is routine
    key hygiene, the second makes every verdict in the chain read INVALID.

    The registry therefore keeps the public key and a ``retired_at_height``
    boundary instead of deleting the entry. No boundary — still trusted.
    """
    for signer in trusted_signers(chain_addr):
        if signer.get("sha256fgpt") != sha256fgpt:
            continue
        retired = signer.get("retired_at_height")
        return retired is None or int(height) <= int(retired)
    return False


def retire_signer(chain_addr: str, sha256fgpt: str,
                  at_height: int | None = None) -> dict[str, Any]:
    """Mark a registered signer as retired as of ``at_height`` (default: now).

    The public key stays on disk and the entry stays in ``info.yaml``; only the
    boundary changes, so pre-retirement blocks keep verifying. Re-registering
    the same key later clears the boundary (explicit re-trust).
    """
    info = read_info(chain_addr)
    signers = info.get("trusted_signers", [])
    target = next((s for s in signers if s.get("sha256fgpt") == sha256fgpt), None)
    if target is None:
        raise KeyError("No registered signer has that fingerprint.")
    if target.get("retired_at_height") is not None:
        return dict(target)
    target["retired_at_height"] = int(
        last_height(chain_addr) if at_height is None else at_height)
    write_info(chain_addr, info)
    return dict(target)


# --------------------------------------------------------------------------
# Payload construction
# --------------------------------------------------------------------------


def issue_payload(document: dict[str, Any],
                  content_hash_algo: str = "sha3_512") -> dict[str, Any]:
    """Build an ISSUE payload for a document with PersonalParticulars,
    AcademicInfo and DocumentInfo. Only hashes go on the chain."""
    for key in ("PersonalParticulars", "AcademicInfo", "DocumentInfo"):
        if key not in document:
            raise ValueError(f"Document missing required section: {key}")

    h_pp = crypto_util.hash_json(document["PersonalParticulars"], content_hash_algo)
    h_ai = crypto_util.hash_json(document["AcademicInfo"], content_hash_algo)
    h_di = crypto_util.hash_json(document["DocumentInfo"], content_hash_algo)
    h_doc = crypto_util.merkle_root([h_pp, h_ai, h_di], content_hash_algo)

    return {
        "action": "ISSUE",
        "HashedPersonalParticulars": h_pp,
        "HashedAcademicInfo": h_ai,
        "HashedDocumentInfo": h_di,
        "HashedDocument": h_doc,
        "DocumentInfo": document["DocumentInfo"],
    }


def revoke_payload(hashed_document: str,
                   content_hash_algo: str = "sha3_512") -> dict[str, Any]:
    """Build a REVOKE payload that references a previously issued document."""
    return {
        "action": "REVOKE",
        "HashedDocument": hashed_document,
    }


# --------------------------------------------------------------------------
# Block files
# --------------------------------------------------------------------------


def _block_path(chain_addr: str, height: int) -> str:
    return os.path.join(chain_addr, "blocks", f"block-{height:09d}.json")


def _write_block_file(chain_addr: str, block: dict[str, Any]) -> None:
    """Atomic write: write to ``.temp`` then rename (per TODO.md)."""
    final_path = _block_path(chain_addr, block["height"])
    temp_path = final_path + ".temp"
    with open(temp_path, "w", encoding="utf-8") as fh:
        json.dump(block, fh, ensure_ascii=False, indent=2)
    os.replace(temp_path, final_path)


def load_block(chain_addr: str, height: int) -> dict[str, Any]:
    """Load a block JSON file (no verification).

    Raises ChainDataError when the file is missing or corrupted, so callers
    can distinguish "data is broken" from "block is fine".
    """
    try:
        with open(_block_path(chain_addr, height), encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise ChainDataError(f"block {height} is missing") from exc
    except (OSError, ValueError) as exc:
        raise ChainDataError(
            f"block {height} file is corrupted ({type(exc).__name__})"
        ) from exc


def last_height(chain_addr: str) -> int:
    return int(read_info(chain_addr).get("last_block_height", -1))


# --------------------------------------------------------------------------
# Append
# --------------------------------------------------------------------------


def append_block(chain_addr: str, payload: dict[str, Any],
                 signers: list[tuple[str, Any]],
                 content_hash_algo: str | None = None) -> dict[str, Any]:
    """Append a signed block.

    ``signers`` is a list of ``(ds_algo, private_key)`` — every listed signer
    signs the payload hash (message = b64urlsafe HMAC(key=nonce, msg=payload
    hash, algo=contentHashAlgo)); each signer gets its own random nonce.

    Returns the new block dict.
    """
    if not signers:
        raise ValueError("At least one data signer is required to append a block.")

    info = read_info(chain_addr)
    content_hash_algo = content_hash_algo or info.get("content_hash_algo", "sha3_512")
    height = int(info.get("last_block_height", -1)) + 1

    prev_block = load_block(chain_addr, height - 1)
    prev_hash_sum = crypto_util.hash_json(prev_block, content_hash_algo)

    ds_infos = []
    for ds_algo, priv_key in signers:
        nonce, signature = crypto_util.sign_json(
            payload, ds_algo, priv_key, content_hash_algo=content_hash_algo
        )
        sha1fgpt, sha256fgpt = crypto_util.getfgpt(priv_key.public_key())
        ds_infos.append({
            "DSsha1fgpt": sha1fgpt,
            "DSsha256fgpt": sha256fgpt,
            "DSver": 1,
            "DSAlgo": ds_algo,
            "DSnonce": nonce,
            "DSignature": signature,
            # Batch U4.1: the record now states what was signed, so a verifier
            # can recompute it independently. Absent on older blocks, which is
            # tolerated on read (see _verify_payload_signatures).
            "DSmessageDigest": crypto_util.message_digest_b64(
                payload, nonce, content_hash_algo),
            "DSscheme": SIGNATURE_SCHEME,
        })

    block = {
        "height": height,
        "contentHashAlgo": content_hash_algo,
        "prevHashSum": prev_hash_sum,
        "timestamp": time.time_ns(),
        "schemaVersion": BLOCK_SCHEMA_VERSION,
        "payload": payload,
        "DataSignatureInfo": ds_infos,
    }

    _write_block_file(chain_addr, block)
    info["last_block_height"] = height
    write_info(chain_addr, info)
    return block


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


def _verify_payload_signatures(chain_addr: str,
                               block: dict[str, Any]) -> tuple[bool, list[str]]:
    """All DataSignatureInfo entries must belong to trusted signers and verify.

    Returns (ok, reasons).

    Blocks written before batch U4.1 have no ``DSscheme`` / ``DSmessageDigest``
    fields; those are accepted as-is (the signature check is unchanged). When
    the fields are present they must agree with what this verifier recomputes —
    an unrecognised scheme is a failure, never a silent pass.
    """
    problems: list[str] = []
    algo = block.get("contentHashAlgo", "sha3_512")
    for ds in block.get("DataSignatureInfo", []):
        sha256fgpt = ds.get("DSsha256fgpt", "")
        if not is_trusted(chain_addr, sha256fgpt):
            problems.append(f"untrusted signer fingerprint {sha256fgpt[:20]}...")
            continue
        # U16: a retired key is still registered (its old blocks must verify),
        # but anything it signs after the boundary is not trusted.
        block_height = int(block.get("height") or 0)
        if not signer_trusted_at(chain_addr, sha256fgpt, block_height):
            problems.append(
                f"signer {sha256fgpt[:20]}... signed block #{block_height} "
                f"after it was retired")
            continue
        signer = next(s for s in trusted_signers(chain_addr)
                      if s["sha256fgpt"] == sha256fgpt)
        pub_key = crypto_util.fetch_pubkey(_signer_pub_path(chain_addr, sha256fgpt))

        scheme = ds.get("DSscheme")
        if scheme is not None and scheme != SIGNATURE_SCHEME:
            problems.append(f"unknown signature scheme {scheme!r}")
            continue

        recorded_digest = ds.get("DSmessageDigest")
        if recorded_digest is not None:
            expected = crypto_util.message_digest_b64(
                block["payload"], str(ds.get("DSnonce", "")), algo)
            if recorded_digest != expected:
                problems.append("recorded message digest does not match payload")
                continue

        ok = crypto_util.verify_ds(
            block["payload"],
            ds.get("DSAlgo", ""),
            pub_key,
            ds.get("DSignature", ""),
            ds.get("DSnonce", ""),
            content_hash_algo=algo,
        )
        if not ok:
            problems.append(f"signature invalid for {signer['name']}")
        elif ds.get("DSAlgo") != signer.get("ds_algo"):
            problems.append(f"algorithm mismatch for {signer['name']}")
    return (not problems), problems


def _signer_pub_path(chain_addr: str, sha256fgpt: str) -> str:
    # fingerprints are colon-separated hex — colons are illegal in file names
    safe = sha256fgpt.replace(":", "")[:24]
    return os.path.join(chain_addr, "keys", f"signer-{safe}.pem")


def verify_block(chain_addr: str, height: int) -> dict[str, Any]:
    """Verify a single block: payload signatures + hash links to i-1 and i+1.

    Returns a dict of per-check booleans (no exception for a bad block).
    """
    result: dict[str, Any] = {"height": height, "exists": True, "ok": True,
                              "checks": {}}

    try:
        block = load_block(chain_addr, height)
    except (FileNotFoundError, ChainDataError):
        result["exists"] = False
        result["ok"] = False
        result["checks"] = {"missing": False}
        return result

    algo = block.get("contentHashAlgo", "sha3_512")

    # 1. recomputed block hash matches recorded prevHashSum of the next block
    block_hash = crypto_util.hash_json(block, algo)
    if height + 1 <= last_height(chain_addr):
        try:
            nxt = load_block(chain_addr, height + 1)
        except (FileNotFoundError, ChainDataError):
            link_ok = False  # next block missing or corrupted
        else:
            link_ok = nxt.get("prevHashSum", "") == block_hash
        result["checks"]["next_link"] = link_ok
        if not link_ok:
            result["ok"] = False
    else:
        result["checks"]["next_link"] = True  # tip block: nothing links to it yet

    # 2. prevHashSum matches the actual hash of the previous block
    if height == 0:
        prev_ok = block.get("prevHashSum", "") == ""
    else:
        try:
            prev = load_block(chain_addr, height - 1)
        except (FileNotFoundError, ChainDataError):
            prev_ok = False  # previous block missing or corrupted
        else:
            prev_ok = block.get("prevHashSum", "") == crypto_util.hash_json(prev, algo)
    result["checks"]["prev_link"] = prev_ok
    if not prev_ok:
        result["ok"] = False

    # 3. height field is consistent with the file name
    if height != block.get("height"):
        result["checks"]["height"] = False
        result["ok"] = False
    else:
        result["checks"]["height"] = True

    # 4. payload signatures (all signers trusted + cryptographically valid)
    sig_ok, problems = _verify_payload_signatures(chain_addr, block)
    result["checks"]["signatures"] = sig_ok
    result["signature_problems"] = problems
    if not sig_ok:
        result["ok"] = False

    return result


def verify_chain(chain_addr: str) -> tuple[bool, list[dict[str, Any]]]:
    """Verify the whole chain from the genesis block.

    Scans every block (no early exit) and returns (ok, report) where report
    contains one entry per height — all problems are surfaced at once.

    U9-A: the result is cached against the block-directory fingerprint for at
    most ``CHAIN_INTEGRITY_TTL`` seconds. Re-verifying every signature on every
    request was the single largest cost in `verify_document()` (O(height) ML-DSA
    verifications per request). The returned report is shared — callers must
    treat it as read-only.
    """
    ttl = float(getattr(cfg, "CHAIN_INTEGRITY_TTL", 0) or 0)
    fingerprint = _chain_fingerprint(chain_addr)
    now = time.time()
    if ttl > 0:
        with _CACHE_LOCK:
            cached = _CHAIN_CACHE.get(chain_addr)
        if cached is not None and cached[0] == fingerprint and now - cached[1] < ttl:
            return cached[2], cached[3]

    report = []
    for height in range(0, last_height(chain_addr) + 1):
        report.append(verify_block(chain_addr, height))
    ok = all(r["ok"] for r in report)
    # Only store the verdict if it is still fresh when the scan finishes. A
    # TTL shorter than one scan would otherwise mint an entry that is already
    # expired the moment it lands — it can never be read, only evicted, and
    # the cache quietly does nothing. `now` is when the scan started, so this
    # is the honest measure of how old the verdict is.
    if ttl > 0 and time.time() - now < ttl:
        with _CACHE_LOCK:
            _CHAIN_CACHE[chain_addr] = (fingerprint, now, ok, report)
    return ok, report


def fetch_block(chain_addr: str, height: int) -> dict[str, Any] | None:
    """Return the (verified) block JSON, or None if missing/broken."""
    res = verify_block(chain_addr, height)
    if not res["ok"]:
        return None
    return load_block(chain_addr, height)


# --------------------------------------------------------------------------
# Status lookup (revocation)
# --------------------------------------------------------------------------


def _status_index(chain_addr: str) -> dict[str, dict[str, Any]]:
    """Build (and cache) hash -> {issue/revoke heights, first issue time}.

    U9-A: `fetch_status()` scanned and JSON-parsed every block on every call,
    and `verify_document()` scanned the chain a second time to find the ISSUE
    block. One pass over the block directory builds both answers. Keyed on the
    same fingerprint + TTL as `verify_chain()`, so a new block invalidates it.

    U13 F3: the first ISSUE block's timestamp rides along (in seconds), so a
    holder page can show "when was this issued" without a second chain scan.
    """
    ttl = float(getattr(cfg, "CHAIN_INDEX_TTL", 0) or 0)
    fingerprint = _chain_fingerprint(chain_addr)
    now = time.time()
    if ttl > 0:
        with _CACHE_LOCK:
            cached = _INDEX_CACHE.get(chain_addr)
        if cached is not None and cached[0] == fingerprint and now - cached[1] < ttl:
            return cached[2]

    index: dict[str, dict[str, Any]] = {}
    for height in range(1, last_height(chain_addr) + 1):
        # An unreadable block must NOT be skipped here: swallowing it would
        # turn a corrupt chain into "not revoked / not found" (200 instead of
        # 503, INVALID instead of CHAIN DATA CORRUPT). The scan propagates
        # ChainDataError exactly like the old per-request scan did.
        block = load_block(chain_addr, height)
        payload = block.get("payload", {})
        hashed = payload.get("HashedDocument")
        if not hashed:
            continue
        action = payload.get("action")
        bucket = index.setdefault(hashed, {"issue": [], "revoke": [],
                                           "issue_ts": None})
        if action == "ISSUE":
            bucket["issue"].append(height)
            if bucket.get("issue_ts") is None:
                ts = block.get("timestamp") or 0
                bucket["issue_ts"] = (ts / 1e9) if ts else None
        elif action == "REVOKE":
            bucket["revoke"].append(height)
    if ttl > 0 and time.time() - now < ttl:
        with _CACHE_LOCK:
            _INDEX_CACHE[chain_addr] = (fingerprint, now, index)
    return index


def fetch_status(chain_addr: str, hashed_document: str) -> dict[str, Any]:
    """Return the on-chain status of a document hash.

    {"issued": bool, "revoked": bool, "issue_heights": [...],
     "revoke_heights": [...], "issued_at": float | None}
    """
    bucket = _status_index(chain_addr).get(hashed_document) or {}
    return {
        "issued": bool(bucket.get("issue")),
        "revoked": bool(bucket.get("revoke")),
        "issue_heights": list(bucket.get("issue", [])),
        "revoke_heights": list(bucket.get("revoke", [])),
        "issued_at": bucket.get("issue_ts"),
    }


# --------------------------------------------------------------------------
# Verifier — 6 checks on a presented document
# --------------------------------------------------------------------------


def verify_document(chain_addr: str, document: dict[str, Any]) -> dict[str, Any]:
    """Verify a presented document against the chain.

    Checks:
      1. chain_integrity   — whole chain verifies from genesis
      2. signer_trusted    — every signer of the ISSUE block is registered
      3. on_chain_record   — an ISSUE block exists for this document hash
      4. hash_match        — recomputed part hashes match the block payload
      5. signature_valid   — the ISSUE block signatures verify
      6. not_revoked       — no REVOKE block references the document hash

    Returns a dict with per-check booleans and a final "valid" verdict.
    """
    algo = read_info(chain_addr).get("content_hash_algo", "sha3_512")
    h_pp = crypto_util.hash_json(document.get("PersonalParticulars", {}), algo)
    h_ai = crypto_util.hash_json(document.get("AcademicInfo", {}), algo)
    h_di = crypto_util.hash_json(document.get("DocumentInfo", {}), algo)
    h_doc = crypto_util.merkle_root([h_pp, h_ai, h_di], algo)

    result = {
        "chain_integrity": None,
        "signer_trusted": None,
        "on_chain_record": None,
        "hash_match": None,
        "signature_valid": None,
        "not_revoked": None,
        "hashed_document": h_doc,
    }

    # 1. chain integrity
    chain_ok, report = verify_chain(chain_addr)
    result["chain_integrity"] = chain_ok

    # 3. on-chain record (find the latest ISSUE block for this doc)
    # U9-A: the index answers "which heights hold this hash" in one cached pass
    # instead of scanning (and JSON-parsing) the whole chain per request. Latest
    # ISSUE wins, same as the old reverse scan.
    issue_block = None
    issue_heights = _status_index(chain_addr).get(h_doc, {}).get("issue", [])
    if issue_heights:
        issue_block = load_block(chain_addr, issue_heights[-1])
    result["on_chain_record"] = issue_block is not None

    if issue_block is not None:
        # 2. all ISSUE signers are trusted
        fgpts = [ds.get("DSsha256fgpt", "") for ds in issue_block.get("DataSignatureInfo", [])]
        result["signer_trusted"] = all(is_trusted(chain_addr, f) for f in fgpts)

        # 4. hash match (document parts must produce the same hashes)
        payload = issue_block["payload"]
        result["hash_match"] = (
            payload.get("HashedPersonalParticulars") == h_pp
            and payload.get("HashedAcademicInfo") == h_ai
            and payload.get("HashedDocumentInfo") == h_di
            and payload.get("HashedDocument") == h_doc
        )

        # 5. signature valid (re-verify payload signature with trusted pub keys)
        # U9-B: the chain replay computed above already verified this very
        # block's signatures (verify_block check "signatures" = trusted +
        # cryptographically valid). Re-running ML-DSA verification per request
        # duplicated that work, so reuse the replay result when it covers this
        # height; otherwise fall back to verifying the block directly.
        replayed = next((r for r in report
                         if r.get("height") == issue_heights[-1]), None)
        if replayed is not None and replayed.get("checks", {}).get("signatures"):
            result["signature_valid"] = True
        else:
            sig_ok, _ = _verify_payload_signatures(chain_addr, issue_block)
            result["signature_valid"] = sig_ok
    else:
        result["signer_trusted"] = False
        result["hash_match"] = False
        result["signature_valid"] = False

    # 6. not revoked
    status = fetch_status(chain_addr, h_doc)
    result["not_revoked"] = not status["revoked"]

    result["valid"] = all(result[k] for k in (
        "chain_integrity", "signer_trusted", "on_chain_record",
        "hash_match", "signature_valid", "not_revoked",
    ))
    return result


def show_verdict(result: dict[str, Any]) -> None:
    """Pretty-print the six checks and the final verdict."""
    labels = {
        "chain_integrity": "1. Chain integrity intact",
        "signer_trusted": "2. Signer is trusted",
        "on_chain_record": "3. Document is on the chain",
        "hash_match": "4. Hash matches on-chain record",
        "signature_valid": "5. Signer signature is valid",
        "not_revoked": "6. Document is not revoked",
    }
    width = max(len(v) for v in labels.values())
    for check, label in labels.items():
        value = result.get(check)
        if value is None:
            continue
        mark = "PASS" if value else "FAIL"
        print(f"  [{mark}] {label.ljust(width)} -> {value}")
    print("-" * 70)
    print("  FINAL VERDICT:", "VALID" if result["valid"] else "INVALID")
