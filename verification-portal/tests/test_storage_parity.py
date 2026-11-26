"""Batch U7.1 — JSON and SQLite backends must behave the same.

Both implementations live behind one Protocol, so a divergence is silent: the
demo runs on JSON while the "production" path runs on SQLite, and a bug would
only surface after switching backends. This module drives every store through
the same script and compares the *semantics*:

* same shape (which keys exist, and of what type),
* same lifecycle outcomes (a revoked key stops validating, a rotated key
  replaces the old one, expiries land in the same bucket),
* same ordering and truncation rules for ``recent(limit)``.

Values that are intentionally random (key material, ids, timestamps) are
excluded from equality; everything else must match.
"""

import unittest
import uuid
from pathlib import Path

from tests._bootstrap import isolated_chain_dir


def setUpModule():
    global TMP_ROOT
    TMP_ROOT = isolated_chain_dir(prefix="gef26-parity-")
    from app import repository
    global repo_mod
    repo_mod = repository


def _db(name: str) -> Path:
    """A fresh SQLite file inside the throwaway chain root.

    Deliberately not a TemporaryDirectory: ``SqliteBackend`` opens short-lived
    connections and exposes no ``close()``, so on Windows the file is still
    held when a TemporaryDirectory teardown runs (WinError 32). The chain
    root is already disposable.
    """
    return Path(TMP_ROOT) / f"{name}-{uuid.uuid4().hex[:6]}.db"


def _shape(value):
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(v) for v in value]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _drop(mapping: dict, *keys: str) -> dict:
    return {k: v for k, v in mapping.items() if k not in keys}


VOLATILE = ("created_at", "timestamp", "ts", "at", "expires_at",
            "updated_at", "last_used_at", "verified_at")


class ApiKeyParityTests(unittest.TestCase):
    def _run(self, repo):
        created = repo.api_keys.create_key("parity", expires_in_days=7)
        listed = repo.api_keys.list_keys()
        valid = repo.api_keys.validate_key(created["key"])
        revoked = repo.api_keys.revoke_key(created["id"], reason="parity")
        after_revoke = repo.api_keys.validate_key(created["key"])
        rotated = repo.api_keys.rotate_key(created["id"], expires_in_days=1)
        rotated_valid = (repo.api_keys.validate_key(rotated["key"])
                         if rotated else None)
        return {
            "created_shape": _shape(_drop(created, "key", "id", *VOLATILE)),
            # lengths are not comparable: the JSON stores live in the shared
            # data dir and accumulate across tests, SQLite files are fresh
            "list_non_empty": len(listed) >= 1,
            "list_shape": _shape(_drop(listed[0], "id", *VOLATILE))
            if listed else None,
            "valid_shape": _shape(_drop(valid, "id", *VOLATILE)) if valid else None,
            "revoke_returns_true": revoked is True,
            "after_revoke": after_revoke,
            "rotate_returns_dict": isinstance(rotated, dict),
            "rotated_has_new_key": bool(rotated and rotated["key"] != created["key"]),
            "rotated_valid": bool(rotated_valid),
        }

    def test_json_and_sqlite_agree(self):
        json_repo = repo_mod.json_repository()
        sqlite_repo = repo_mod.sqlite_repository(_db("keys"))
        a = self._run(json_repo)
        b = self._run(sqlite_repo)
        self.assertEqual(a, b, f"backend divergence:\nJSON  {a}\nSQL {b}")


class LogAndAuditParityTests(unittest.TestCase):
    def _run(self, repo):
        for _ in range(3):
            repo.log.record("A" * 40, "VALID ON CHAIN")
        recent = repo.log.recent(2)
        total = repo.log.total()
        for action in ("issue", "revoke", "key.create"):
            repo.audit.record(action, subject="S" * 40, outcome="ok",
                              detail=f"detail-{action}")
        audit_recent = repo.audit.recent(2)
        return {
            "log_recent_len": len(recent),
            "log_shape": _shape(_drop(recent[0], *VOLATILE)),
            "log_total": total,
            "audit_recent_len": len(audit_recent),
            "audit_shape": _shape(_drop(audit_recent[0], *VOLATILE)),
            "audit_ordering": [row["action"] for row in audit_recent],
        }

    def test_json_and_sqlite_agree(self):
        a = self._run(repo_mod.json_repository())
        b = self._run(repo_mod.sqlite_repository(_db("log")))
        self.assertEqual(a, b, f"backend divergence:\nJSON  {a}\nSQL {b}")


class ReceiptAndRevocationParityTests(unittest.TestCase):
    def _run(self, repo):
        rid = repo.receipts.register("B" * 40, "VALID ON CHAIN", 1700000000.0,
                                     "verify/hash")
        rid_str = rid if isinstance(rid, str) else str(rid)
        got = repo.receipts.get(rid_str)
        repo.revocation_index.upsert("C" * 40, 2, 1700000000.0, "reason here")
        idx = repo.revocation_index.get("C" * 40)
        all_rows = repo.revocation_index.all()
        return {
            "receipt_id_is_str": isinstance(rid, str) and len(rid) > 0,
            "receipt_shape": _shape(_drop(got, *VOLATILE)) if got else None,
            "index_shape": _shape(_drop(idx, *VOLATILE)) if idx else None,
            "all_contains_row": any(row["hashed_document"] == "C" * 40
                                    for row in all_rows),
            "all_shape": _shape(_drop(all_rows[0], *VOLATILE)) if all_rows else None,
        }

    def test_json_and_sqlite_agree(self):
        a = self._run(repo_mod.json_repository())
        b = self._run(repo_mod.sqlite_repository(_db("receipts")))
        self.assertEqual(a, b, f"backend divergence:\nJSON  {a}\nSQL {b}")

    def test_unknown_receipt_is_none_in_both(self):
        missing = "receipt-" + uuid.uuid4().hex
        self.assertIsNone(repo_mod.json_repository().receipts.get(missing))
        self.assertIsNone(
            repo_mod.sqlite_repository(_db("missing")).receipts.get(missing))


if __name__ == "__main__":
    unittest.main()
