"""Batch U9-B — the audit trail must say *who* did it.

U7 left "审计不含操作者身份" open. The fix is invisible to every existing
call site: ``audit.record()`` keeps its signature, the request middleware
resolves the caller (API-key id → role token → anonymous) into a context
variable, and both storage backends persist it.

What these tests pin down:

* the actor reaches the JSON store and the SQLite store,
* consecutive requests do not inherit each other's actor,
* an unresolved (wrong) role token stays anonymous in the audit trail even
  though the endpoint itself rejects it,
* rows written before this batch (no actor column value) still read back.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from tests._bootstrap import isolated_chain_dir  # noqa: E402


def setUpModule():
    isolated_chain_dir(prefix="gef26-u9b-")
    from app import audit as audit_mod
    from app import chain_service, config, main
    from app.repository import JsonAuditStore, SqliteAuditStore, SqliteBackend
    global audit, cs, cfg, main_mod, JsonAuditStore_, SqliteAuditStore_, SqliteBackend_
    audit, cs, cfg, main_mod = audit_mod, chain_service, config, main
    JsonAuditStore_, SqliteAuditStore_, SqliteBackend_ = (
        JsonAuditStore, SqliteAuditStore, SqliteBackend)
    cs.ensure_chain()


def _doc(index: int) -> dict:
    return {
        "PersonalParticulars": {
            "Surname": f"ACTOR{index:03d}",
            "GivenNames": "AUDIT TEST",
            "StudentID": f"9050{index:04d}",
            "Sex": "F",
            "DOB": "19990101",
        },
        "AcademicInfo": {
            "DegreeName": f"Actor Degree {index}",
            "DegreeStartDate": "20220901",
            "DegreeEndDate": "20260801",
            "Honour": "Pass",
        },
        "DocumentInfo": {
            "DocType": "Diploma",
            "IssuingO": "UNIVERSITY OF UTOPIA",
            "IssuingOU": "FACULTY OF ENGINEERING",
            "DateOfIssue": "20260901",
            "AuthorizedSignature": "REGISTRAR",
        },
    }


class ActorThroughRequestsTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_mod.app)
        self._token = cfg.ADMIN_TOKEN
        cfg.ADMIN_TOKEN = "u9b-admin-token"

    def tearDown(self):
        cfg.ADMIN_TOKEN = self._token
        audit.clear_actor()

    def _last_audit(self) -> dict:
        return audit.recent(1)[0]

    def test_admin_token_is_recorded_as_a_role_actor(self):
        res = self.client.post("/api/issue", json={"document": _doc(1)},
                              headers={"X-Admin-Token": "u9b-admin-token"})
        self.assertEqual(res.status_code, 200)
        rec = self._last_audit()
        self.assertEqual(rec["action"], "issue")
        self.assertEqual(rec["actor"], "role:admin")

    def test_unauthenticated_request_is_anonymous_in_the_trail(self):
        # token configured, no header → 401 and no audit row at all
        before = len(audit.recent(200))
        res = self.client.post("/api/issue", json={"document": _doc(2)})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(len(audit.recent(200)), before,
                         "a rejected request must not write an audit event")

    def test_no_token_configured_is_the_demo_open_case(self):
        cfg.ADMIN_TOKEN = None
        res = self.client.post("/api/issue", json={"document": _doc(3)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._last_audit()["actor"], "anonymous")

    def test_wrong_role_token_writes_nothing(self):
        before = len(audit.recent(200))
        res = self.client.post("/api/issue", json={"document": _doc(4)},
                               headers={"X-Admin-Token": "not-the-token"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(len(audit.recent(200)), before)
        self.assertEqual(audit.current_actor(), audit.ANONYMOUS)

    def test_actor_does_not_leak_between_requests(self):
        self.client.post("/api/issue", json={"document": _doc(5)},
                         headers={"X-Admin-Token": "u9b-admin-token"})
        cfg.ADMIN_TOKEN = None
        self.client.post("/api/issue", json={"document": _doc(6)})
        self.assertEqual(self._last_audit()["actor"], "anonymous")
        self.assertEqual(audit.current_actor(), audit.ANONYMOUS)


class StorePersistsActorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gef26-u9b-"))
        audit.set_actor("role:issuer")

    def tearDown(self):
        audit.clear_actor()
        for child in self.tmp.iterdir():
            child.unlink()
        self.tmp.rmdir()

    def test_json_store_writes_the_actor(self):
        store = JsonAuditStore_(self.tmp / "audit-log.jsonl")
        rec = store.record("issue", "AA", "ok", "Diploma")
        self.assertEqual(rec["actor"], "role:issuer")
        self.assertEqual(store.recent(1)[0]["actor"], "role:issuer")

    def test_sqlite_store_writes_the_actor(self):
        backend = SqliteBackend_(self.tmp / "portal.sqlite")
        store = SqliteAuditStore_(backend)
        store.record("revoke", "BB", "ok", "reason")
        rec = store.recent(1)[0]
        self.assertEqual(rec["actor"], "role:issuer")
        backend.close()

    def test_legacy_sqlite_rows_without_an_actor_still_read(self):
        backend = SqliteBackend_(self.tmp / "legacy.sqlite")
        backend.execute("INSERT INTO audit_events (time, action, subject,"
                        " outcome, detail, actor)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (1, "issue", "CC", "ok", None, None))
        rec = SqliteAuditStore_(backend).recent(1)[0]
        self.assertEqual(rec["action"], "issue")
        self.assertNotIn("actor", rec)
        backend.close()

    def test_clear_actor_falls_back_to_anonymous(self):
        audit.clear_actor()
        self.assertEqual(audit.current_actor(), audit.ANONYMOUS)


if __name__ == "__main__":
    unittest.main()
