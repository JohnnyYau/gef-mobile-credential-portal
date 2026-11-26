"""Extras round 6 — employer pack: batch verify, API keys, signed revocation
status list, receipt registry, revocation reason/effective date.

Runs in private mode (admin available) on its own isolated chain: the module
reloads config + chain_service + main with a fresh CHAIN_DIR, so it is
order-independent within the shared unittest process.
"""

import importlib
import os
import unittest

from fastapi.testclient import TestClient

from tests._bootstrap import isolated_chain_dir


def setUpModule():
    isolated_chain_dir(prefix="gef26-emp-")
    os.environ.pop("PUBLIC_MODE", None)
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.chain_service as cs_mod
    importlib.reload(cs_mod)
    from app import main as _m
    importlib.reload(_m)
    global app, chain_service, statuslist, client
    from app import chain_service as _cs
    from app import statuslist as _sl
    app = _m.app
    chain_service = _cs
    statuslist = _sl
    client = TestClient(app)


def tearDownModule():
    # restore the pre-existing shared chain + private mode so later modules
    # in the same unittest process see the state the earlier modules set up
    os.environ.pop("PUBLIC_MODE", None)
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.chain_service as cs_mod
    importlib.reload(cs_mod)
    from app import main as _m
    importlib.reload(_m)


class EmployerPackTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        creds = chain_service.demo_credentials()
        cls.valid_hash = creds["diploma"]["hashed_document"]

    def test_batch_verify_valid(self):
        resp = client.post("/api/verify/batch", json={"hashes": [self.valid_hash]})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["summary"]["total"], 1)
        self.assertEqual(data["summary"]["valid"], 1)
        row = data["results"][0]
        self.assertEqual(row["verdict"], "VALID ON CHAIN")
        self.assertTrue(row["receipt_id"].startswith("RCP-"))

    def test_batch_verify_mixed(self):
        hashes = [self.valid_hash, "Z" * 44, "not-a-hash", "", 12345]
        resp = client.post("/api/verify/batch", json={"hashes": hashes})
        self.assertEqual(resp.status_code, 200)
        summary = resp.json()["summary"]
        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["valid"], 1)
        self.assertEqual(summary["not_found"], 1)
        self.assertEqual(summary["error"], 3)  # bad-format, empty, non-string

    def test_batch_verify_limit(self):
        resp = client.post("/api/verify/batch", json={"hashes": ["a" * 44] * 501})
        self.assertEqual(resp.status_code, 422)

    def test_batch_verify_bad_body(self):
        resp = client.post("/api/verify/batch", json={"hashes": "x"})
        self.assertEqual(resp.status_code, 422)

    def test_statuslist_signed_and_stable(self):
        from cryptography.hazmat.primitives import serialization

        from app import crypto_util

        payload, etag = statuslist.build(force=True)
        self.assertEqual(payload["schema"], "gef26.statuslist.v2")
        sig = payload["signature"]
        self.assertEqual(sig["algo"], "ML_DSA_65")
        # U17: v1 carried no nonce, so the signature could not be recomputed by
        # anyone — and it stamped SIGNER_NAME from config, which keeps naming the
        # first signer after a rotation.
        self.assertTrue(sig["nonce"])
        self.assertIn("sha256fgpt", sig)
        names = {s["sha256fgpt"]: s["name"]
                 for s in chain_service.list_signers()["signers"]}
        self.assertEqual(sig["signer"], names[sig["sha256fgpt"]])

        body = {k: v for k, v in payload.items() if k != "signature"}
        entry = next(s for s in chain_service.public_keys()["signers"]
                     if s["sha256fgpt"] == sig["sha256fgpt"])
        pub = serialization.load_pem_public_key(entry["pubkey_pem"].encode())
        self.assertTrue(crypto_util.verify_ds(body, sig["algo"], pub, sig["value"],
                                              sig["nonce"], "sha3_512"))
        # digest is stable while the chain does not change
        payload2, etag2 = statuslist.build()
        self.assertEqual(etag, etag2)

    def test_statuslist_http_etag(self):
        first = client.get("/api/statuslist")
        self.assertEqual(first.status_code, 200)
        etag = first.headers.get("etag")
        self.assertTrue(etag)
        second = client.get("/api/statuslist", headers={"If-None-Match": etag})
        self.assertEqual(second.status_code, 304)

    def test_api_key_flow(self):
        created = client.post("/api/admin/apikeys", json={"name": "HR bot"})
        self.assertEqual(created.status_code, 200)
        data = created.json()
        self.assertTrue(data["key"])  # raw key returned exactly once
        kid = data["id"]

        # list shows it, without the raw key
        listed = client.get("/api/admin/apikeys").json()["keys"]
        match = next(k for k in listed if k["id"] == kid)
        self.assertEqual(match["name"], "HR bot")
        self.assertNotIn("key", match)

        # bad key -> 401
        resp = client.get("/api/verify/" + self.valid_hash,
                          headers={"Authorization": "Bearer nope"})
        self.assertEqual(resp.status_code, 401)

        # good key -> higher budget path works
        resp = client.get("/api/verify/" + self.valid_hash,
                          headers={"Authorization": "Bearer " + data["key"]})
        self.assertEqual(resp.status_code, 200)

        # revoke kills it
        self.assertTrue(client.delete(f"/api/admin/apikeys/{kid}").status_code == 200)
        resp = client.get("/api/verify/" + self.valid_hash,
                          headers={"Authorization": "Bearer " + data["key"]})
        self.assertEqual(resp.status_code, 401)

    def test_revoke_reason_surfaces(self):
        h = chain_service.ensure_revoked_sample()
        # revoke the demo credential? no — it already is. Issue a fresh one.
        doc = {
            **chain_service.SAMPLE_DIPLOMA,
            "DocumentInfo": {
                **chain_service.SAMPLE_DIPLOMA["DocumentInfo"],
                "DocNumber": "EMP-REV-1",
            },
        }
        issued = client.post("/api/issue", json={"document": doc}).json()
        h = issued["hashed_document"]
        resp = client.post("/api/revoke", json={
            "hashed_document": h,
            "reason": "administrative error",
            "effective_at": 1700000000,
        })
        self.assertEqual(resp.status_code, 200)
        verify = client.get(f"/api/verify/{h}").json()
        self.assertEqual(verify["verdict"], "REVOKED")
        self.assertEqual(verify["reason"], "administrative error")
        self.assertEqual(verify["effective_at"], 1700000000)
        self.assertTrue(verify["receipt_id"].startswith("RCP-"))

    def test_receipt_registry_roundtrip(self):
        resp = client.get(f"/api/verify/{self.valid_hash}")
        rid = resp.json()["receipt_id"]
        rec = client.get(f"/api/receipt/{rid}")
        self.assertEqual(rec.status_code, 200)
        self.assertEqual(rec.json()["hashed_document"], self.valid_hash)
        self.assertIn(rec.json()["verdict"], ("VALID ON CHAIN", "VALID"))
        bad = client.get("/api/receipt/NOPE")
        self.assertEqual(bad.status_code, 422)
        missing = client.get("/api/receipt/RCP-00000000-AAAA")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
