"""disclosure.py — section-bound disclosure views (batch U4.4).

Why sections: ``issue_payload`` puts three section hashes on chain and
``HashedDocument`` is the Merkle root over them::

    h_pp = hash(PersonalParticulars)
    h_ai = hash(AcademicInfo)
    h_di = hash(DocumentInfo)
    HashedDocument = merkle_root([h_pp, h_ai, h_di])

So a view that shows *sections* can be checked cryptographically, without any
new chain field: recompute the hash of each disclosed section, take the Merkle
root with the on-chain hashes for the hidden ones, and compare against the
on-chain ``HashedDocument``. If it matches, the disclosed values are provably
the same ones behind the on-chain credential.

What is still NOT proven: anything about the hidden section beyond its hash. A
holder cannot prove "DOB is after 2000" or "StudentID starts with 22" — that is
out of scope. ``assurance`` states this in every view.

Field-level commitments are also offered, but they are explicitly *not*
verifiable against the chain: the section hash covers the whole section, so a
hidden field inside a disclosed section breaks that section's hash. They exist
for holder-to-verifier later opening only, and say so.
"""

import copy
import secrets

from . import crypto_util

SECTIONS = ("PersonalParticulars", "AcademicInfo", "DocumentInfo")

# The section that carries identity data; hiding it is the common case.
DEFAULT_HIDDEN_SECTIONS = ("PersonalParticulars",)
FIELD_TAG = "gef-field-v1"


def _leaves(obj, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_leaves(value, path))
        else:
            out[path] = "" if value is None else str(value)
    return out


def _set_nested(target: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = target
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def section_hash(section: dict, algo: str = "sha3_512") -> str:
    return crypto_util.hash_json(section, algo)


def credential_hash(document: dict, algo: str = "sha3_512") -> str:
    """The on-chain ``HashedDocument`` this document would issue to."""
    hashes = [section_hash(document[s], algo) for s in SECTIONS]
    return crypto_util.merkle_root(hashes, algo)


def commit(value: str, salt: str) -> str:
    """Salted field commitment (holder-openable only; not chain-verifiable)."""
    return crypto_util.hash_json({"tag": FIELD_TAG, "salt": salt,
                                  "value": value})


def open_commitment(value: str, salt: str) -> str:
    return commit(value, salt)


def make_disclosure(document: dict, hide_sections=DEFAULT_HIDDEN_SECTIONS,
                    hide_fields=None, algo: str = "sha3_512") -> dict:
    """Build a view: show some sections, hide others, optionally commit fields.

    ``hide_fields`` entries are dotted paths and may only point inside
    *disclosed* sections — hiding a field inside a hidden section would be
    redundant, and hiding one inside a disclosed section invalidates that
    section's hash, which the view reports as ``unbound_sections``.
    """
    missing = [s for s in SECTIONS if s not in document]
    if missing:
        raise ValueError(f"Document missing required section(s): {', '.join(missing)}")
    hidden_sections = list(hide_sections)
    unknown = [s for s in hidden_sections if s not in SECTIONS]
    if unknown:
        raise ValueError(f"Unknown section(s): {', '.join(sorted(unknown))}")
    if len(hidden_sections) == len(SECTIONS):
        raise ValueError("Cannot hide every section — the view would prove nothing.")

    hide_fields = list(hide_fields or [])
    disclosed_sections = [s for s in SECTIONS if s not in hidden_sections]

    disclosed: dict = {}
    commitments: dict = {}
    unbound: list[str] = []
    section_hashes: dict = {}

    for section in disclosed_sections:
        body = document[section]
        leaves = _leaves(body)
        # hide_fields are dotted paths prefixed with the section name;
        # _leaves keys are section-local.
        local = [p.split(".", 1)[1] for p in hide_fields
                 if p.split(".", 1)[0] == section]
        hit = [p for p in local if p in leaves]
        bad = [p for p in local if p not in leaves]
        if bad:
            raise ValueError(f"Unknown field(s) to hide: {', '.join(sorted(bad))}")
        if hit:
            unbound.append(section)
            for path in leaves:
                if path in hit:
                    salt = secrets.token_urlsafe(16)
                    commitments[f"{section}.{path}"] = {
                        "salt": salt, "commitment": commit(leaves[path], salt)}
                else:
                    _set_nested(disclosed, f"{section}.{path}", leaves[path])
            # the shown part no longer hashes to the section hash
            section_hashes[section] = None
        else:
            # deep copy: a view must never alias the caller's document, or
            # editing the view would silently edit the credential.
            disclosed[section] = copy.deepcopy(body)
            section_hashes[section] = section_hash(body, algo)

    hidden_hashes = {s: section_hash(document[s], algo) for s in hidden_sections}

    return {
        "credential_hash": credential_hash(document, algo),
        "content_hash_algo": algo,
        "disclosed_sections": disclosed,
        "hidden_sections": hidden_sections,
        "section_hashes": section_hashes,
        "hidden_section_hashes": hidden_hashes,
        "commitments": commitments,
        "unbound_sections": unbound,
        "assurance": (
            "disclosed sections are cryptographically bound to the on-chain "
            "credential via the section hashes and the Merkle root. Nothing is "
            "proven about the hidden section beyond its hash, and field-level "
            "commitments are holder-openable only — this is not a zero-knowledge "
            "proof."
        ),
    }


def check_against_record(view: dict, record: dict) -> dict:
    """Compare a view with the on-chain ISSUE payload for the same credential.

    Returns ``{ok, reasons, bound_sections}``. Every disclosed section must
    hash to the record's section hash, and the Merkle root over
    (disclosed + hidden hashes) must equal the record's ``HashedDocument``.
    """
    reasons: list[str] = []
    algo = view.get("content_hash_algo") or record.get("contentHashAlgo", "sha3_512")
    record_hash = record.get("HashedDocument")
    if view.get("credential_hash") != record_hash:
        reasons.append("credential_hash does not match the on-chain record")

    disclosed = view.get("disclosed_sections") or {}
    bound: list[str] = []
    for section, body in disclosed.items():
        if section not in SECTIONS:
            reasons.append(f"unknown section {section}")
            continue
        expected = record.get(f"Hashed{section}")
        if not isinstance(body, dict):
            reasons.append(f"section {section} is not an object")
            continue
        actual = section_hash(body, algo)
        if expected is None:
            reasons.append(f"record has no hash for section {section}")
        elif actual != expected:
            reasons.append(f"section {section} does not match the on-chain hash")
        else:
            bound.append(section)

    hidden = view.get("hidden_sections") or []
    for section in hidden:
        if section not in SECTIONS:
            reasons.append(f"unknown section {section}")
    overlap = sorted(set(disclosed) & set(hidden))
    if overlap:
        reasons.append(f"sections both disclosed and hidden: {', '.join(overlap)}")

    # rebuild the root from the record: disclosed hashes are recomputed above,
    # hidden ones come from the record itself.
    if record_hash and not overlap:
        try:
            parts = [record[f"Hashed{s}"] for s in SECTIONS]
            root = crypto_util.merkle_root(parts, algo)
            if root != record_hash:
                reasons.append("on-chain record is internally inconsistent")
        except (KeyError, ValueError):
            reasons.append("on-chain record is missing a section hash")

    return {"ok": not reasons, "reasons": reasons, "bound_sections": bound}
