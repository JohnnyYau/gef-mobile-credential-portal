"""Post-Week-3 extra tests: QR codes, public log, anomaly watch.

Uses an isolated throwaway chain. If run in the same process as other test
modules, toggles the admin rate-limit constant around the burst test and
restores it afterwards.
"""

import json
import os
import shutil
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="portal-feature-test-")
os.environ["CHAIN_DIR"] = os.path.join(_TMP, "test-chain")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app import chain_service  # noqa: E402
from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402


class FeatureTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls._saved_admin = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_ADMIN_MAX = 100000  # burst test issues 21 docs

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admin

    def _sample_hash(self):
        d = self.client.get("/api/demo/credentials").json()
        return d["diploma"]["hashed_document"]

    def test_verify_page_serves_ui(self):
        res = self.client.get("/verify")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Credential Verification Portal", res.text)

    def test_qr_returns_png(self):
        h = self._sample_hash()
        res = self.client.get(f"/api/qr/{h}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "image/png")
        self.assertGreater(len(res.content), 500)

    def test_qr_bad_hash_422(self):
        res = self.client.get("/api/qr/not-a-valid-hash!")
        self.assertEqual(res.status_code, 422)

    def test_log_records_verification_anonymized(self):
        res = self.client.post("/api/verify/document",
                               json={"document": SAMPLE_DIPLOMA})
        self.assertEqual(res.json()["verdict"], "VALID")
        log = self.client.get("/api/log").json()
        self.assertTrue(log["verifications"])
        latest = log["verifications"][-1]
        self.assertEqual(latest["verdict"], "VALID")
        full_hash = res.json()["hashed_document"]
        self.assertEqual(latest["hash_prefix"], full_hash[:12])
        self.assertNotIn(full_hash, json.dumps(log["verifications"]))

    def test_log_chain_tail(self):
        log = self.client.get("/api/log").json()
        self.assertTrue(log["chain_events"])
        actions = {e["action"] for e in log["chain_events"]}
        self.assertIn("ISSUE", actions)
        for e in log["chain_events"]:
            self.assertIn("height", e)
            self.assertIn("hash_prefix", e)

    def test_anomaly_clean_chain(self):
        d = self.client.get("/api/anomalies").json()
        self.assertEqual(d["anomalies"], [])
        self.assertEqual(d["threshold"], 20)
        self.assertEqual(len(d["hourly_issues"]), 24)

    def test_anomaly_flags_burst(self):
        for _ in range(21):  # same doc, 21 ISSUE blocks in the same hour
            res = self.client.post("/api/issue", json={"document": SAMPLE_DIPLOMA})
            self.assertEqual(res.status_code, 200)
        d = self.client.get("/api/anomalies").json()
        self.assertTrue(d["anomalies"], "expected a signer-velocity anomaly")
        a = d["anomalies"][0]
        self.assertGreaterEqual(a["credential_count"], 21)
        self.assertEqual(a["threshold"], 20)
        self.assertIn("severity", a)

    def test_qr_after_issue(self):
        res = self.client.post("/api/issue", json={"document": SAMPLE_DIPLOMA})
        h = res.json()["hashed_document"]
        qr = self.client.get(f"/api/qr/{h}")
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.headers["content-type"], "image/png")


if __name__ == "__main__":
    unittest.main()
