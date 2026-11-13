"""Extras-round-2 tests: verifiable PDFs, student lookup, signer admin,
email notifications, persistent public log, IsolationForest method flag.

Uses an isolated throwaway chain (fresh CHAIN_DIR + fresh log files under it).
"""

import io
import json
import os
import shutil
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="portal-extra2-test-")
os.environ["CHAIN_DIR"] = os.path.join(_TMP, "test-chain")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app import chain_service, notifier, pdf_diploma, public_log  # noqa: E402
from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402


class Extra2TestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls._saved_admin = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_ADMIN_MAX = 100000

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admin

    def _issue(self, email=None):
        body = {"document": SAMPLE_DIPLOMA}
        if email:
            body["student_email"] = email
        return self.client.post("/api/issue", json=body)

    # ---- verifiable PDF ----
    def test_issue_returns_pdf_url(self):
        res = self._issue()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["pdf_url"].startswith("/api/pdf/"))

    def test_pdf_roundtrip_verifies(self):
        res = self._issue()
        h = res.json()["hashed_document"]
        pdf = self.client.get(f"/api/pdf/{h}")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        # extract the embedded JSON and verify it exactly
        doc = pdf_diploma.extract_credential(pdf.content)
        self.assertEqual(doc, SAMPLE_DIPLOMA)
        verdict = self.client.post("/api/verify/document", json={"document": doc})
        self.assertEqual(verdict.json()["verdict"], "VALID")

    def test_verify_pdf_upload_endpoint(self):
        res = self._issue()
        h = res.json()["hashed_document"]
        pdf = self.client.get(f"/api/pdf/{h}").content
        v = self.client.post(
            "/api/verify/document",
            files={"file": ("diploma.pdf", pdf, "application/pdf")},
        )
        self.assertEqual(v.status_code, 200)
        self.assertEqual(v.json()["verdict"], "VALID")

    def test_pdf_unknown_hash_404(self):
        res = self.client.get("/api/pdf/" + "A" * 64)
        self.assertEqual(res.status_code, 404)

    def test_bad_pdf_upload_rejected(self):
        fake = b"%PDF-1.4\nnot a real pdf with no attachment"
        v = self.client.post(
            "/api/verify/document",
            files={"file": ("fake.pdf", fake, "application/pdf")},
        )
        self.assertEqual(v.status_code, 422)
        self.assertIn("credential.json", v.json()["detail"])

    # ---- student self-service ----
    def test_student_lookup(self):
        r = self.client.get("/api/student/22000000?dob=19880808")
        self.assertEqual(r.status_code, 200)
        creds = r.json()["credentials"]
        self.assertGreaterEqual(len(creds), 2)  # seed diploma + transcript
        self.assertTrue(all(c["verdict"] == "VALID ON CHAIN" for c in creds))

    def test_student_lookup_wrong_dob_404(self):
        r = self.client.get("/api/student/22000000?dob=19990101")
        self.assertEqual(r.status_code, 404)

    def test_student_lookup_no_dob_404(self):
        r = self.client.get("/api/student/22000000")
        self.assertEqual(r.status_code, 404)

    def test_student_lookup_unknown_id(self):
        r = self.client.get("/api/student/99999999?dob=19880808")
        self.assertEqual(r.status_code, 404)

    # ---- signer admin ----
    def test_signers_list(self):
        r = self.client.get("/api/signers")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["signers"])
        self.assertIn("active", r.json())

    def test_add_and_activate_signer(self):
        r = self.client.post("/api/signers", json={"name": "DEPT OF LAW", "ds_algo": "ec.secp256r1"})
        self.assertEqual(r.status_code, 200)
        fp = r.json()["sha256fgpt"]
        self.assertEqual(r.json()["name"], "DEPT OF LAW")
        # activate it, then the active signer switches
        act = self.client.post("/api/signers/active", json={"sha256fgpt": fp})
        self.assertEqual(act.status_code, 200)
        self.assertEqual(act.json()["active"], fp)
        listing = self.client.get("/api/signers").json()
        self.assertEqual(listing["active"], fp)
        self.assertEqual(len(listing["signers"]), 2)  # seed signer + new

    def test_activate_unknown_signer_422(self):
        r = self.client.post("/api/signers/active", json={"sha256fgpt": "Z" * 44})
        self.assertEqual(r.status_code, 422)

    def test_issue_by_active_signer(self):
        self.client.post("/api/signers", json={"name": "ACTIVE GUY", "ds_algo": "RSA_PSS_2048"})
        # newest signer isn't active yet; activate first registered? No — activate the new one:
        fp = self.client.get("/api/signers").json()["signers"][-1]["sha256fgpt"]
        self.client.post("/api/signers/active", json={"sha256fgpt": fp})
        res = self._issue()
        self.assertEqual(res.status_code, 200)
        info = chain_service.chain_info()
        # the ISSUE block should be signed by the active signer
        from app import blockchain_util
        block = blockchain_util.load_block(str(chain_service.CHAIN_DIR), res.json()["height"])
        ds_fp = block["DataSignatureInfo"][0]["DSsha256fgpt"]
        self.assertEqual(ds_fp, fp)

    # ---- notifications ----
    def test_notification_dry_run(self):
        res = self._issue(email="student@example.com")
        note = res.json()["notification"]
        self.assertEqual(note["status"], "dry-run")
        self.assertEqual(note["to"], "student@example.com")
        self.assertIn("verify?hash=", note["detail"])

    def test_notification_skipped_without_email(self):
        res = self._issue()
        self.assertEqual(res.json()["notification"]["status"], "skipped")

    def test_notifications_list(self):
        self._issue(email="a@example.com")
        r = self.client.get("/api/notifications")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["notifications"])

    # ---- persistence of the public log ----
    def test_public_log_persists_across_instances(self):
        h = self.client.get("/api/demo/credentials").json()["diploma"]["hashed_document"]
        self.client.get(f"/api/verify/{h}")
        log_path = public_log._log_path()
        self.assertTrue(log_path.exists())
        # a fresh instance must reload from disk
        fresh = public_log.PublicLog()
        self.assertGreaterEqual(len(fresh.recent()), 1)
        self.assertEqual(fresh.recent()[-1]["hash_prefix"], h[:12])

    # ---- anomaly method flag ----
    def test_anomaly_method_reported(self):
        r = self.client.get("/api/anomalies")
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.json()["method"], ("isolation_forest", "rule_based"))
        self.assertEqual(len(r.json()["hourly_issues"]), 24)


if __name__ == "__main__":
    unittest.main()
