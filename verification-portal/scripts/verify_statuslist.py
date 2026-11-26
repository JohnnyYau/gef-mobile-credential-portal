"""Verify a cached status list offline — with no call back to the portal.

The portal says an employer can cache ``GET /api/statuslist`` and answer "is
this credential revoked?" until the next refresh. That claim only holds if the
signature can actually be checked, which needs two things the portal had never
handed out together before U17: the nonce (to recompute the signed message) and
the signer's public key (``GET /api/signers/keys``).

Save both responses as files, then:

    python scripts/verify_statuslist.py statuslist.json signer-keys.json
    python scripts/verify_statuslist.py statuslist.json signer-keys.json \\
        --hash GFiY4d67yoi8...
    python scripts/verify_statuslist.py statuslist.json signer-keys.json \\
        --expect f2:6d:75:... --pin trust-anchor.pin.json

U18 — a signature check alone only proves the list and the anchor agree with
each other. If both files came from the same hijacked source, an attacker can
re-key them and sign a fake list that says a revoked credential is fine.
``--expected`` (``--expect``) names the fingerprint you already know out of
band; ``--pin`` records the anchor's fingerprint set on first use and refuses
any later anchor that differs. A damaged pin file fails closed — deleting it
does not reset trust.

U20 — a strict pin has no way to follow a legitimate key rotation: the only
"fix" was to delete the pin, i.e. to reset trust silently. ``--pin-update``
makes that reset an explicit, audited act: the anchor is rewritten **only if
the list itself verifies**, the old/new fingerprint sets and a timestamp are
appended to the pin file's ``history``, and the output says what changed. A
missing ``--expect`` is reported as a warning, because in that case the only
thing vouching for the new key is the same channel that delivered it.

Exit code 0 = signature valid (and, when asked, anchored); 1 = invalid, missing
anchor, a list signed by a retired key after its boundary, or an anchor that
does not match the pin. Nothing here touches the network or the chain directory.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization  # noqa: E402

from app.crypto_util import getfgpt, verify_ds  # noqa: E402

DEFAULT_HASH_ALGO = "sha3_512"
PIN_SCHEMA_V1 = "gef26.trust-anchor.pin.v1"
PIN_SCHEMA = "gef26.trust-anchor.pin.v2"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fingerprints(anchors):
    """The anchor's signer fingerprints, sorted — what a pin records."""
    return sorted({str(s.get("sha256fgpt"))
                   for s in anchors.get("signers", []) if s.get("sha256fgpt")})


def verify(status, anchors, content_hash_algo=None, expected=None):
    """Check the signature; returns a dict with ``ok`` and a human ``reason``."""
    sig = status.get("signature") or {}
    fingerprint = sig.get("sha256fgpt")
    if not fingerprint:
        return {"ok": False,
                "reason": "status list carries no signer fingerprint "
                          "(a v1 list cannot be verified — rebuild from v2)"}
    if not sig.get("nonce") or not sig.get("value"):
        return {"ok": False, "reason": "signature is missing its nonce or value"}

    entry = next((s for s in anchors.get("signers", [])
                  if s.get("sha256fgpt") == fingerprint), None)
    if entry is None:
        return {"ok": False, "reason": f"signer {fingerprint} is not in the trust anchor"}

    # U18: the fingerprint you already know beats any anchor you just fetched.
    if expected:
        allowed = {str(e).strip().lower() for e in expected if str(e).strip()}
        if fingerprint.lower() not in allowed:
            return {"ok": False,
                    "reason": f"signing key {fingerprint} is not in the expected set "
                              f"({', '.join(sorted(allowed))})"}

    if not entry.get("pubkey_pem"):
        return {"ok": False, "reason": "trust anchor has no public key for that signer"}

    public_key = serialization.load_pem_public_key(entry["pubkey_pem"].encode("utf-8"))
    # The anchor must be describing the key it actually contains; otherwise a
    # wrong file would look like a broken signature instead of a wrong anchor.
    _, actual = getfgpt(public_key)
    if actual != fingerprint:
        return {"ok": False,
                "reason": "public key in the anchor does not match its fingerprint"}

    algo = sig.get("algo") or entry.get("ds_algo")
    if entry.get("ds_algo") and algo != entry["ds_algo"]:
        return {"ok": False, "reason": f"signature algo {algo} != anchor algo {entry['ds_algo']}"}

    height = (status.get("snapshot") or {}).get("height")
    retired_at = entry.get("retired_at_height")
    if retired_at is not None and isinstance(height, int) and height > retired_at:
        return {"ok": False,
                "reason": f"list was signed at height {height}, after the key was "
                          f"retired at #{retired_at}"}

    body = {k: v for k, v in status.items() if k != "signature"}
    algo_hash = (content_hash_algo
                 or (anchors.get("chain") or {}).get("content_hash_algo")
                 or DEFAULT_HASH_ALGO)
    if not verify_ds(body, algo, public_key, sig["value"], sig["nonce"], algo_hash):
        return {"ok": False, "reason": "signature does not verify over the list body"}

    return {
        "ok": True,
        "reason": "signature valid",
        "schema": status.get("schema"),
        "height": height,
        "revoked_count": (status.get("counts") or {}).get("revoked"),
        "signer": {"name": entry.get("name"), "sha256fgpt": fingerprint,
                   "retired_at_height": retired_at},
    }


def lookup(status, fingerprint, ok):
    """Answer the employer's actual question from the list alone."""
    revoked = status.get("revoked") or []
    for row in revoked:
        if str(row.get("hash")) == fingerprint:
            return {"revoked": True, "reason": row.get("reason"),
                    "effective_at": row.get("effective_at")}
    # Only a verified list can be read as "not revoked".
    return {"revoked": False, "trustworthy": bool(ok)}


def read_pin(path):
    """Load a pin file; raise rather than guess if it is not what we wrote.

    Both v1 (no ``history``) and v2 are accepted: the fingerprint set is the
    part that matters, and an older pin stays usable until it is next updated.
    """
    data = _read(path)
    pins = data.get("sha256fgpt")
    if not isinstance(pins, list) or not pins:
        raise ValueError("pin file has no sha256fgpt list")
    history = data.get("history")
    if history is not None and not isinstance(history, list):
        raise ValueError("pin file history is not a list")
    return data


def write_pin(path, anchors, history=None):
    """Record the anchor's fingerprint set — trust on first use (or on update).

    Written to a temporary file and renamed into place: the fail-closed rule
    turns a half-written pin into a permanently unreadable one, so a crash must
    not be able to produce that state. ``history`` (U20) is the audit trail of
    every explicit ``--pin-update``; it is absent on a fresh pin.
    """
    target = Path(path)
    payload = {"schema": PIN_SCHEMA, "sha256fgpt": fingerprints(anchors),
               "chain_name": (anchors.get("chain") or {}).get("name")}
    if history:
        payload["history"] = history
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    tmp.replace(target)
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("statuslist", help="JSON saved from GET /api/statuslist")
    ap.add_argument("anchors", help="JSON saved from GET /api/signers/keys")
    ap.add_argument("--hash", help="credential hash to look up in the list")
    ap.add_argument("--content-hash-algo", default=None,
                    help=f"override the payload hash (default {DEFAULT_HASH_ALGO})")
    ap.add_argument("--expect", action="append", default=None, metavar="FINGERPRINT",
                    help="fingerprint that must be the one that signed (repeatable); "
                         "use the value you already know out of band")
    ap.add_argument("--pin", default=None, metavar="FILE",
                    help="record the anchor's fingerprints on first use and require "
                         "the same set afterwards")
    ap.add_argument("--pin-update", action="store_true",
                    help="rewrite the pin after a key rotation — only when the list "
                         "verifies, and the change is appended to the pin's history")
    args = ap.parse_args(argv)
    if args.pin_update and not args.pin:
        ap.error("--pin-update needs --pin (there is no pin file to update)")

    status = _read(args.statuslist)
    anchors = _read(args.anchors)

    result = None
    pin_state = None
    pending_update = None
    pin_path = Path(args.pin) if args.pin else None
    if pin_path:
        current = fingerprints(anchors)
        if pin_path.exists():
            try:
                pinned = read_pin(pin_path)
            except (OSError, ValueError) as exc:
                # Fail closed. Treating a damaged pin as "first use" would let
                # anyone reset the trust anchor by deleting or breaking the file.
                result = {"ok": False, "anchor_pin": "unreadable",
                          "reason": f"pin file {pin_path} is unreadable ({exc}); "
                                    "refusing to treat that as first use"}
            else:
                pinned_set = sorted(pinned["sha256fgpt"])
                if pinned_set != current:
                    diff = {"removed_since_pin": sorted(set(pinned_set) - set(current)),
                            "added_since_pin": sorted(set(current) - set(pinned_set))}
                    if args.pin_update:
                        pending_update = {"pinned": pinned, "diff": diff}
                    else:
                        result = {
                            "ok": False,
                            "anchor_pin": "mismatch",
                            "reason": "trust anchor does not match the pinned fingerprints "
                                      "(after confirming the new key out of band, re-run with "
                                      "--pin-update to record the rotation)",
                            **diff,
                        }
                else:
                    pin_state = "matched"
        else:
            write_pin(pin_path, anchors)
            pin_state = "created"

    if result is None:
        result = verify(status, anchors, args.content_hash_algo, args.expect)
        if pending_update is not None and result["ok"]:
            previous = pending_update["pinned"]
            entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "previous": previous.get("sha256fgpt"),
                     "added": pending_update["diff"]["added_since_pin"],
                     "removed": pending_update["diff"]["removed_since_pin"],
                     "tool": "verify_statuslist.py --pin-update"}
            history = list(previous.get("history") or []) + [entry]
            write_pin(pin_path, anchors, history)
            update = {"pin_file": str(pin_path), "added": entry["added"],
                      "removed": entry["removed"], "history_length": len(history)}
            if not args.expect:
                update["warning"] = ("no --expect was given: the new key is vouched for "
                                     "only by the same channel that delivered the anchor")
            result["anchor_pin"] = "updated"
            result["pin_update"] = update
        elif pending_update is not None:
            # The anchor changed and was not accepted — but the list is also not
            # trustworthy, so there is nothing worth recording. Leave the pin as
            # it was and say why.
            result["anchor_pin"] = "mismatch"
            result["reason"] = (f"{result.get('reason', 'list did not verify')}; "
                                "pin not updated because the list did not verify")
            result.update(pending_update["diff"])
        elif pin_state:
            result["anchor_pin"] = pin_state
    if args.hash:
        result["lookup"] = lookup(status, args.hash, result["ok"])

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
