"""query_service.py — read-side verification and lookups (internal, U1.2).

Everything that answers a question about the chain: lifecycle status, the
six-check verdicts, the anonymised public tail, the issuer-side student
registry and the snapshot id.
"""

import json

from . import blockchain_util, crypto_util
from .chain_core import (
    SAMPLE_DIPLOMA,
    SAMPLE_TRANSCRIPT,
    ensure_chain,
)
from .config import CHAIN_DIR, CHAIN_TAIL_LIMIT


def _corrupt_verdict(exc: Exception, hashed_document=None) -> dict:
    """Structured verdict when chain data is unreadable/corrupted."""
    return {
        "chain_integrity": False,
        "signer_trusted": False,
        "on_chain_record": None,
        "hash_match": None,
        "signature_valid": False,
        "not_revoked": None,
        "hashed_document": hashed_document,
        "valid": False,
        "verdict": "CHAIN DATA CORRUPT",
        "chain_error": str(exc),
    }


def status(hashed_document: str) -> dict:
    ensure_chain()
    return blockchain_util.fetch_status(str(CHAIN_DIR), hashed_document)


def verify_document(document: dict) -> dict:
    """Full six-check verification of a presented credential document."""
    for key in ("PersonalParticulars", "AcademicInfo", "DocumentInfo"):
        if key not in document:
            raise ValueError(f"Document missing required section: {key}")
    ensure_chain()
    try:
        result = blockchain_util.verify_document(str(CHAIN_DIR), document)
    except blockchain_util.ChainDataError as exc:
        return _corrupt_verdict(
            exc, blockchain_util.issue_payload(document)["HashedDocument"]
        )
    if result["valid"]:
        result["verdict"] = "VALID"
    elif not result["not_revoked"]:
        result["verdict"] = "REVOKED"
    else:
        result["verdict"] = "INVALID"
    return result


def verify_hash(hashed_document: str) -> dict:
    """Hash-level verification: every check that is computable without the
    full document. Check 4 (hash_match) requires the document, so it is
    reported as ``None`` with a note — upload the document for the full check.
    """
    ensure_chain()
    chain = str(CHAIN_DIR)

    try:
        chain_ok, _ = blockchain_util.verify_chain(chain)

        issue_block = issue_height = None
        for height in range(blockchain_util.last_height(chain), 0, -1):
            block = blockchain_util.load_block(chain, height)
            payload = block.get("payload", {})
            if (payload.get("action") == "ISSUE"
                    and payload.get("HashedDocument") == hashed_document):
                issue_block, issue_height = block, height
                break

        signer_trusted = signature_valid = False
        if issue_block is not None:
            fgpts = [d.get("DSsha256fgpt", "") for d in
                     issue_block.get("DataSignatureInfo", [])]
            signer_trusted = bool(fgpts) and all(
                blockchain_util.is_trusted(chain, f) for f in fgpts
            )
            signature_valid = blockchain_util.verify_block(chain, issue_height)["checks"].get(
                "signatures", False
            )

        lifecycle = blockchain_util.fetch_status(chain, hashed_document)
    except blockchain_util.ChainDataError as exc:
        return _corrupt_verdict(exc, hashed_document)

    result = {
        "chain_integrity": chain_ok,
        "signer_trusted": signer_trusted,
        "on_chain_record": issue_block is not None,
        "hash_match": None,  # requires the full document
        "signature_valid": signature_valid,
        "not_revoked": not lifecycle["revoked"],
        "hashed_document": hashed_document,
        "status": lifecycle,
    }
    if lifecycle["revoked"]:
        result["verdict"] = "REVOKED"
    elif issue_block is None:
        result["verdict"] = "NOT FOUND"
    elif chain_ok and signer_trusted and signature_valid:
        result["verdict"] = "VALID ON CHAIN"
    else:
        result["verdict"] = "INVALID"
    return result


def on_chain_payload(hashed_document: str) -> dict | None:
    """The ISSUE payload on chain for this credential hash, or None.

    Batch U4.4 needs the stored section hashes to check a disclosure view
    against the ledger; this returns exactly that record, not a verdict.
    """
    ensure_chain()
    chain = str(CHAIN_DIR)
    try:
        for height in range(blockchain_util.last_height(chain), 0, -1):
            block = blockchain_util.load_block(chain, height)
            payload = block.get("payload", {})
            if (payload.get("action") == "ISSUE"
                    and payload.get("HashedDocument") == hashed_document):
                return payload
    except (OSError, blockchain_util.ChainDataError, ValueError):
        return None
    return None


def chain_snapshot_id() -> str:
    """'<height>:<hash of last block>' — changes only when the chain does."""
    ensure_chain()
    chain = str(CHAIN_DIR)
    height = blockchain_util.last_height(chain)
    try:
        last = blockchain_util.load_block(chain, height)
        return f"{height}:{crypto_util.hash_json(last, 'sha3_512')[:24]}"
    except blockchain_util.ChainDataError:  # corrupted tail still yields an id
        return f"{height}:corrupt"


def demo_credentials() -> dict:
    """Sample credentials (issued at seed time) for the UI's try-it buttons."""
    out = {}
    for kind, doc in (("diploma", SAMPLE_DIPLOMA), ("transcript", SAMPLE_TRANSCRIPT)):
        out[kind] = {
            "document": doc,
            "hashed_document": blockchain_util.issue_payload(doc)["HashedDocument"],
        }
    return out


def chain_tail(limit=CHAIN_TAIL_LIMIT) -> list:
    """Last ``limit`` blocks, anonymized (hash prefixes only) for the public log."""
    ensure_chain()
    chain = str(CHAIN_DIR)
    last = blockchain_util.last_height(chain)
    out = []
    for height in range(max(1, last - limit + 1), last + 1):
        try:
            block = blockchain_util.load_block(chain, height)
        except blockchain_util.ChainDataError:
            out.append({"height": height, "action": "CORRUPT", "hash_prefix": None,
                        "timestamp": None, "signer_fp": None})
            continue
        payload = block.get("payload", {})
        ds = block.get("DataSignatureInfo", [])
        out.append({
            "height": height,
            "action": payload.get("action"),
            "hash_prefix": (payload.get("HashedDocument") or "")[:12] or None,
            "timestamp": block.get("timestamp"),
            "signer_fp": (ds[0].get("DSsha256fgpt", "")[:12] if ds else None),
        })
    return out


def _verdict_row(hashed_document: str, doc_type: str, degree: str) -> dict:
    status = blockchain_util.fetch_status(str(CHAIN_DIR), hashed_document)
    heights = status.get("issue_heights") or []
    return {
        "hashed_document": hashed_document,
        "doc_type": doc_type or "CREDENTIAL",
        "degree": degree or "—",
        # U13 F3: fetch_status reports heights plural; the old single-key read
        # silently returned None, so every UI "issued at block N" was blank.
        "issued_height": heights[0] if heights else None,
        "issued_at": status.get("issued_at"),
        "revoked": status.get("revoked", False),
        "verdict": "REVOKED" if status.get("revoked") else "VALID ON CHAIN",
    }


def _holder_index_rows(student_id: str) -> list:
    """PII-free rows written beside each credential (U12 R5)."""
    index_dir = CHAIN_DIR / "holder_index"
    if not index_dir.exists():
        return []
    rows = []
    for f in sorted(index_dir.glob("*.json")):
        try:
            row = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if row.get("sid") == student_id and row.get("hashed_document"):
            rows.append(row)
    return rows


def student_credentials(student_id: str, dob: str | None = None) -> dict:
    """Issuer-side student lookup.

    The chain stores only hashes. Two portals-side sources can answer this:

    * ``holder_index/`` — one PII-free row per credential (StudentID, hash,
      type, degree). This is the path a shipped bundle uses: it carries no
      names, DOB or e-mail, so it can be distributed.
    * ``rawjsondocs/`` — the issuer's full copies, kept for RAG and PDF
      rendering. Used as a fallback for chains built before R5, and the only
      place a DOB can be compared.

    ``dob`` is accepted for backward compatibility but is not consulted on the
    index path: R3 removed DOB as a public gate, so nothing here relies on it.
    """
    ensure_chain()
    rows = _holder_index_rows(student_id)
    if rows:
        return {
            "student_id": student_id,
            "credentials": [
                _verdict_row(r["hashed_document"],
                             r.get("doc_type"), r.get("degree"))
                for r in rows
            ],
        }

    raw_dir = CHAIN_DIR / "rawjsondocs"
    matches = []
    if raw_dir.exists():
        for f in sorted(raw_dir.glob("*.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pp = doc.get("PersonalParticulars") or {}
            if pp.get("StudentID") != student_id:
                continue
            if dob and pp.get("DOB") != dob:
                continue
            h = blockchain_util.issue_payload(doc)["HashedDocument"]
            docinfo = doc.get("DocumentInfo") or {}
            ai = doc.get("AcademicInfo") or {}
            matches.append(_verdict_row(h, docinfo.get("DocType"),
                                        ai.get("DegreeName")))
    return {"student_id": student_id, "credentials": matches}
