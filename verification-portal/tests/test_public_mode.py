"""Extras round 5 — public verifier mode (PUBLIC_MODE=1).

Public mode disables every admin endpoint (403), adds /api/version and a
REVOKED landing sample (issued + revoked on the chain exactly once), and keeps
the verification surface fully usable.

Runs in its own process state: the module sets PUBLIC_MODE=1 before importing
the app and restores the environment afterwards, so it can share the unittest
process with the other suites.
"""

import importlib
import os
import unittest

from fastapi.testclient import TestClient

from tests._bootstrap import isolated_chain_dir


def setUpModule():
    os.environ["PUBLIC_MODE"] = "1"
    os.environ["APP_VERSION"] = "6.0.0"
    isolated_chain_dir(prefix="gef26-pub-")
    import app.config as cfg_mod
    importlib.reload(cfg_mod)          # re-evaluate PUBLIC_MODE from env
    import app.chain_service as cs_mod
    importlib.reload(cs_mod)
    global client, app_mod
    from app import main as _m
    importlib.reload(_m)
    app_mod = _m
    client = TestClient(_m.app)


def tearDownModule():
    os.environ.pop("PUBLIC_MODE", None)
    os.environ.pop("APP_VERSION", None)
    # restore private-mode state for any module that runs after this one
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.chain_service as cs_mod
    importlib.reload(cs_mod)
    from app import main as _m
    importlib.reload(_m)


class PublicModeTest(unittest.TestCase):

    def test_public_mode_403_admin_issue(self):
        resp = client.post("/api/issue", json={
            "document": app_mod.chain_service.SAMPLE_DIPLOMA})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("public verifier mode", resp.json()["detail"])

    def test_public_mode_403_admin_revoke(self):
        resp = client.post("/api/revoke", json={
            "hashed_document": "a" * 44})
        self.assertEqual(resp.status_code, 403)

    def test_version_identity_public(self):
        resp = client.get("/api/version")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["public_mode"])
        self.assertEqual(data["version"], "6.0.0")
        self.assertEqual(data["app"], "Gef26 credential verification portal")

    def test_demo_credentials_revoked_sample(self):
        resp = client.get("/api/demo/credentials")
        self.assertEqual(resp.status_code, 200)
        creds = resp.json()
        self.assertIn("revoked_sample", creds)
        rs = creds["revoked_sample"]
        self.assertTrue(rs["hashed_document"])
        self.assertIsInstance(rs["document"], dict)
        # the landing sample must actually be revoked on the chain
        v = client.get(f"/api/verify/{rs['hashed_document']}")
        self.assertEqual(v.status_code, 200)
        self.assertEqual(v.json()["verdict"], "REVOKED")

    def test_revoked_sample_issued_once(self):
        rs = client.get("/api/demo/credentials").json()["revoked_sample"]
        h = rs["hashed_document"]
        st = client.get(f"/api/status/{h}").json()
        self.assertEqual(len(st["issue_heights"]), 1)
        self.assertGreaterEqual(len(st["revoke_heights"]), 1)

    def test_verification_still_public(self):
        # the VALID sample remains verifiable in public mode
        creds = client.get("/api/demo/credentials").json()
        h = creds["diploma"]["hashed_document"]
        resp = client.get(f"/api/verify/{h}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("VALID ON CHAIN", resp.json()["verdict"])


if __name__ == "__main__":
    unittest.main()
