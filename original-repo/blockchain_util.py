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

import json
import os
import re
import time

import yaml

import crypto_util

BLOCK_FILE_RE = re.compile(r"^block-(\d{9})\.json$")


# --------------------------------------------------------------------------
# info.yaml (chain metadata + trusted signers)
# --------------------------------------------------------------------------


def _info_path(chain_addr):
    return os.path.join(chain_addr, "info.yaml")


def read_info(chain_addr):
    with open(_info_path(chain_addr), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def write_info(chain_addr, info):
    with open(_info_path(chain_addr), "w", encoding="utf-8") as fh:
        yaml.safe_dump(info, fh, allow_unicode=True, sort_keys=False)


# --------------------------------------------------------------------------
# Chain initialisation
# --------------------------------------------------------------------------


def init_block(chain_addr, chain_name="Gef26-credential-chain",
               content_hash_algo="sha3_512", overwrite=False):
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
        "payload": {
            "action": "GENESIS",
            "chain_name": chain_name,
            "note": "Deterministic genesis block",
        },
        "DataSignatureInfo": [],
    }

    write_info(chain_addr, {
        "chain_name": chain_name,
        "content_hash_algo": content_hash_algo,
        "last_block_height": 0,
        "trusted_signers": [],
    })
    _write_block_file(chain_addr, genesis)
    return genesis


# --------------------------------------------------------------------------
# Trusted signer registry (the chain's "issuer registry")
# --------------------------------------------------------------------------


def register_signer(chain_addr, name, pub_key, ds_algo):
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


def trusted_signers(chain_addr):
    """Return the trusted-signer list [{name, ds_algo, sha1fgpt, sha256fgpt}]."""
    return read_info(chain_addr).get("trusted_signers", [])


def is_trusted(chain_addr, sha256fgpt):
    """True if the given SPKI fingerprint is a registered signer."""
    return any(s.get("sha256fgpt") == sha256fgpt
               for s in trusted_signers(chain_addr))


# --------------------------------------------------------------------------
# Payload construction
# --------------------------------------------------------------------------


def issue_payload(document, content_hash_algo="sha3_512"):
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


def revoke_payload(hashed_document, content_hash_algo="sha3_512"):
    """Build a REVOKE payload that references a previously issued document."""
    return {
        "action": "REVOKE",
        "HashedDocument": hashed_document,
    }


# --------------------------------------------------------------------------
# Block files
# --------------------------------------------------------------------------


def _block_path(chain_addr, height):
    return os.path.join(chain_addr, "blocks", f"block-{height:09d}.json")


def _write_block_file(chain_addr, block):
    """Atomic write: write to ``.temp`` then rename (per TODO.md)."""
    final_path = _block_path(chain_addr, block["height"])
    temp_path = final_path + ".temp"
    with open(temp_path, "w", encoding="utf-8") as fh:
        json.dump(block, fh, ensure_ascii=False, indent=2)
    os.replace(temp_path, final_path)


def load_block(chain_addr, height):
    """Load a block JSON file (no verification)."""
    with open(_block_path(chain_addr, height), "r", encoding="utf-8") as fh:
        return json.load(fh)


def last_height(chain_addr):
    return int(read_info(chain_addr).get("last_block_height", -1))


# --------------------------------------------------------------------------
# Append
# --------------------------------------------------------------------------


def append_block(chain_addr, payload, signers, content_hash_algo=None):
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
        })

    block = {
        "height": height,
        "contentHashAlgo": content_hash_algo,
        "prevHashSum": prev_hash_sum,
        "timestamp": time.time_ns(),
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


def _verify_payload_signatures(chain_addr, block):
    """All DataSignatureInfo entries must belong to trusted signers and verify.

    Returns (ok, reasons).
    """
    payload_hash = crypto_util.hash_json(
        block["payload"], block.get("contentHashAlgo", "sha3_512")
    )
    problems = []
    for ds in block.get("DataSignatureInfo", []):
        sha256fgpt = ds.get("DSsha256fgpt", "")
        if not is_trusted(chain_addr, sha256fgpt):
            problems.append(f"untrusted signer fingerprint {sha256fgpt[:20]}...")
            continue
        signer = next(s for s in trusted_signers(chain_addr)
                      if s["sha256fgpt"] == sha256fgpt)
        pub_key = crypto_util.fetch_pubkey(_signer_pub_path(chain_addr, sha256fgpt))
        ok = crypto_util.verify_ds(
            block["payload"],
            ds.get("DSAlgo", ""),
            pub_key,
            ds.get("DSignature", ""),
            ds.get("DSnonce", ""),
            content_hash_algo=block.get("contentHashAlgo", "sha3_512"),
        )
        if not ok:
            problems.append(f"signature invalid for {signer['name']}")
        elif ds.get("DSAlgo") != signer.get("ds_algo"):
            problems.append(f"algorithm mismatch for {signer['name']}")
    return (not problems), problems


def _signer_pub_path(chain_addr, sha256fgpt):
    # fingerprints are colon-separated hex — colons are illegal in file names
    safe = sha256fgpt.replace(":", "")[:24]
    return os.path.join(chain_addr, "keys", f"signer-{safe}.pem")


def verify_block(chain_addr, height):
    """Verify a single block: payload signatures + hash links to i-1 and i+1.

    Returns a dict of per-check booleans (no exception for a bad block).
    """
    result = {"height": height, "exists": True, "ok": True, "checks": {}}

    try:
        block = load_block(chain_addr, height)
    except FileNotFoundError:
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
        except FileNotFoundError:
            link_ok = False  # next block missing
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
        except FileNotFoundError:
            prev_ok = False  # previous block missing
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


def verify_chain(chain_addr):
    """Verify the whole chain from the genesis block.

    Scans every block (no early exit) and returns (ok, report) where report
    contains one entry per height — all problems are surfaced at once.
    """
    report = []
    for height in range(0, last_height(chain_addr) + 1):
        report.append(verify_block(chain_addr, height))
    ok = all(r["ok"] for r in report)
    return ok, report


def fetch_block(chain_addr, height):
    """Return the (verified) block JSON, or None if missing/broken."""
    res = verify_block(chain_addr, height)
    if not res["ok"]:
        return None
    return load_block(chain_addr, height)


# --------------------------------------------------------------------------
# Status lookup (revocation)
# --------------------------------------------------------------------------


def fetch_status(chain_addr, hashed_document):
    """Return the on-chain status of a document hash.

    {"issued": bool, "revoked": bool, "issue_heights": [...], "revoke_heights": [...]}
    """
    status = {"issued": False, "revoked": False,
              "issue_heights": [], "revoke_heights": []}
    for height in range(1, last_height(chain_addr) + 1):
        block = load_block(chain_addr, height)
        payload = block.get("payload", {})
        if payload.get("HashedDocument") != hashed_document:
            continue
        if payload.get("action") == "ISSUE":
            status["issued"] = True
            status["issue_heights"].append(height)
        elif payload.get("action") == "REVOKE":
            status["revoked"] = True
            status["revoke_heights"].append(height)
    return status


# --------------------------------------------------------------------------
# Verifier — 6 checks on a presented document
# --------------------------------------------------------------------------


def verify_document(chain_addr, document):
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
    issue_block = None
    for height in range(last_height(chain_addr), 0, -1):
        block = load_block(chain_addr, height)
        payload = block.get("payload", {})
        if payload.get("action") == "ISSUE" and payload.get("HashedDocument") == h_doc:
            issue_block = block
            break
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


def show_verdict(result):
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
