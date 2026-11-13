"""Week 3 hardening tests: rate limiting, body/JSON guards, corrupted chain.

NOTE: runs against the shared app instance, so it toggles the module-level
rate-limit constants around its own tests and restores them afterwards.
"""

import json
import os
import shutil
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="portal-harden-test-")
os.environ["CHAIN_DIR"] = os.path.join(_TMP, "test-chain")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402
from app.config import CHAIN_DIR  # noqa: E402

RATE_KEY = {"X-Forwarded-For": "9.9.9.9"}  # isolated limiter bucket


class HardeningTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import chain_service  # local import keeps env order explicit
        chain_service.ensure_chain()  # TestClient lifespan may not run — seed now
        cls.client = TestClient(main.app)
        # snapshot + relax limits for the non-rate-limit tests
        cls._saved_public = main.RATE_LIMIT_PUBLIC_MAX
        cls._saved_admin = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_PUBLIC_MAX = 100000
        main.RATE_LIMIT_ADMIN_MAX = 100000

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)
        main.RATE_LIMIT_PUBLIC_MAX = cls._saved_public
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admin

    def test_rate_limit_429(self):
        main.RATE_LIMIT_PUBLIC_MAX = 3
        try:
            for _ in range(3):
                res = self.client.get("/api/chat/suggestions", headers=RATE_KEY)
                self.assertEqual(res.status_code, 200)
            res = self.client.get("/api/chat/suggestions", headers=RATE_KEY)
            self.assertEqual(res.status_code, 429)
        finally:
            main.RATE_LIMIT_PUBLIC_MAX = 100000

    def test_body_too_large_413(self):
        big = json.dumps({"document": {"pad": "x" * (7 * 1024 * 1024)}})
        res = self.client.post("/api/issue", content=big,
                               headers={"Content-Type": "application/json"})
        self.assertEqual(res.status_code, 413)

    def test_oversize_document_json_422(self):
        doc = json.loads(json.dumps(SAMPLE_DIPLOMA))
        doc["AcademicInfo"]["Blob"] = "x" * (3 * 1024 * 1024)  # > 2 MB JSON cap
        res = self.client.post("/api/verify/document", json={"document": doc})
        self.assertEqual(res.status_code, 422)
        self.assertIn("too large", res.json()["detail"])

    def test_deep_json_422(self):
        nested = {}
        node = nested
        for _ in range(60):  # parses fine, but exceeds MAX_JSON_DEPTH
            node["a"] = {}
            node = node["a"]
        res = self.client.post("/api/verify/document",
                               json={"document": nested})
        self.assertEqual(res.status_code, 422)
        self.assertIn("deep", res.json()["detail"])

    def test_issue_oversize_json_422(self):
        doc = json.loads(json.dumps(SAMPLE_DIPLOMA))
        doc["AcademicInfo"]["Blob"] = "x" * (3 * 1024 * 1024)
        res = self.client.post("/api/issue", json={"document": doc})
        self.assertEqual(res.status_code, 422)

    def test_corrupted_chain_returns_verdict(self):
        chain = str(CHAIN_DIR)
        block_path = os.path.join(chain, "blocks", "block-000000001.json")
        with open(block_path, "rb") as fh:
            original = fh.read()
        with open(block_path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not json !!!")
        try:
            res = self.client.post("/api/verify/document",
                                   json={"document": SAMPLE_DIPLOMA})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["verdict"], "CHAIN DATA CORRUPT")
            self.assertIn("corrupted", data["chain_error"])

            h = self.client.get("/api/demo/credentials").json()["diploma"]["hashed_document"]
            data = self.client.get(f"/api/verify/{h}").json()
            self.assertEqual(data["verdict"], "CHAIN DATA CORRUPT")
        finally:
            with open(block_path, "wb") as fh:  # restore the good block
                fh.write(original)

    def test_status_corrupted_chain_503(self):
        chain = str(CHAIN_DIR)
        block_path = os.path.join(chain, "blocks", "block-000000002.json")
        with open(block_path, "rb") as fh:
            original = fh.read()
        with open(block_path, "w", encoding="utf-8") as fh:
            fh.write("garbage")
        try:
            h = self.client.get("/api/demo/credentials").json()["transcript"]["hashed_document"]
            res = self.client.get(f"/api/status/{h}")
            self.assertEqual(res.status_code, 503)
            self.assertIn("corrupted", res.json()["detail"])
        finally:
            with open(block_path, "wb") as fh:  # restore the good block
                fh.write(original)


if __name__ == "__main__":
    unittest.main()
