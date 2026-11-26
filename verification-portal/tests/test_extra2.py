"""Extras-round-2 tests: verifiable PDFs, student lookup, signer admin,
email notifications, persistent public log, IsolationForest method flag.

Uses an isolated throwaway chain (fresh CHAIN_DIR + fresh log files under it).
"""

import shutil
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(prefix="portal-extra2-test-")

import app.main as main  # noqa: E402
from app import chain_service, pdf_diploma, public_log  # noqa: E402
from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


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

    def _doc_with_sid(self, sid):
        import copy
        doc = copy.deepcopy(SAMPLE_DIPLOMA)
        doc["PersonalParticulars"]["StudentID"] = sid
        return doc

    def _issue_doc(self, doc, email=None):
        body = {"document": doc}
        if email:
            body["student_email"] = email
        return self.client.post("/api/issue", json=body)

    # ---- verifiable PDF ----
    def test_issue_returns_pdf_url(self):
        res = self._issue()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["pdf_url"].startswith("/api/pdf/"))

    def test_pdf_public_is_report_only(self):
        """U13 F1: the anonymous PDF endpoint must not hand out the credential."""
        res = self._issue()
        h = res.json()["hashed_document"]
        pdf = self.client.get(f"/api/pdf/{h}")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertIn('filename="verification-', pdf.headers["content-disposition"])
        self.assertEqual(pdf.headers["cache-control"], "public, max-age=3600")
        with self.assertRaises(ValueError):
            pdf_diploma.extract_credential(pdf.content)

    def test_pdf_roundtrip_verifies(self):
        res = self._issue()
        h = res.json()["hashed_document"]
        pdf = self.client.get(f"/api/admin/pdf/{h}")
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
        pdf = self.client.get(f"/api/admin/pdf/{h}").content
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

    # ---- holder capability links (U12 R3) ----
    def test_dob_lookup_is_gone(self):
        for url in ("/api/student/22000000?dob=19880808",
                    "/api/student/22000000",
                    "/api/student/99999999?dob=19880808"):
            self.assertEqual(self.client.get(url).status_code, 404,
                             "%s must not exist any more" % url)

    def _holder_token(self):
        from app import capability
        from app import query_service
        rows = query_service.student_credentials("22000000")["credentials"]
        self.assertTrue(rows, "seed credential missing")
        return capability.mint("22000000", rows[0]["hashed_document"])

    def test_holder_link_reveals_exactly_one_credential(self):
        token = self._holder_token()
        r = self.client.get("/api/me/" + token)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["student_id"], "22000000")
        self.assertEqual(len(body["credentials"]), 1)
        self.assertEqual(body["credentials"][0]["verdict"], "VALID ON CHAIN")

    def test_holder_page_is_served_for_a_valid_link(self):
        token = self._holder_token()
        r = self.client.get("/me/" + token)
        self.assertEqual(r.status_code, 200)
        self.assertIn("My credential", r.text)

    def test_tampered_token_is_404(self):
        token = self._holder_token()
        body, sig = token.split(".", 1)
        forged = body[:-1] + ("A" if body[-1] != "A" else "B") + "." + sig
        self.assertEqual(self.client.get("/api/me/" + forged).status_code, 404)
        self.assertEqual(self.client.get("/me/" + forged).status_code, 404)

    def test_wrong_signature_is_404(self):
        body, _sig = self._holder_token().split(".", 1)
        self.assertEqual(self.client.get("/api/me/" + body + ".nope").status_code, 404)

    def test_expired_token_is_404(self):
        import json
        import time
        from app import capability, query_service
        rows = query_service.student_credentials("22000000")["credentials"]
        payload = {"sid": "22000000", "h": rows[0]["hashed_document"],
                   "exp": int(time.time()) - 60, "v": 1}
        body = capability._b64(json.dumps(payload, separators=(",", ":"),
                                          sort_keys=True).encode())
        token = body + "." + capability._sign(body)
        self.assertEqual(self.client.get("/api/me/" + token).status_code, 404)

    def test_link_cannot_be_used_for_another_student(self):
        # token for 22000000 must not answer for any other sid: the sid is signed
        token = self._holder_token()
        payload_b64 = token.split(".", 1)[0]
        self.assertNotIn("99999999", payload_b64)
        self.assertEqual(self.client.get("/api/me/" + token).json()["student_id"],
                         "22000000")

    def test_holder_index_rows_carry_no_pii(self):
        from app import chain_service
        index = chain_service.CHAIN_DIR / "holder_index"
        self.assertTrue(index.exists(), "issuing must write a holder index row")
        rows = list(index.glob("*.json"))
        self.assertTrue(rows)
        for f in rows:
            text = f.read_text(encoding="utf-8")
            for key in ('"DOB"', '"Email"', '"Name"', '"MobileNo"', '"Sex"'):
                self.assertNotIn(key, text, f"{f.name} must stay PII-free")

    def test_lookup_still_works_with_raw_documents_missing(self):
        # R5: a public instance ships holder_index/ without rawjsondocs/.
        from app import chain_service
        chain_dir = chain_service.CHAIN_DIR
        raw = chain_dir / "rawjsondocs"
        if not raw.exists():
            self.skipTest("no rawjsondocs in this fixture")
        parked = chain_dir / "rawjsondocs.parked"
        raw.rename(parked)
        try:
            result = chain_service.student_credentials("22000000")
            self.assertTrue(result["credentials"],
                            "holder_index/ alone must resolve the student")
        finally:
            parked.rename(raw)

    # ---- signer admin ----
    def test_signers_list(self):
        r = self.client.get("/api/signers")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["signers"])
        self.assertIn("active", r.json())

    def test_minting_requires_staff_auth(self):
        from app import config as cfg
        old = cfg.ADMIN_TOKEN
        cfg.ADMIN_TOKEN = "r3-staff-token"
        try:
            r = self.client.get(
                "/api/holder-link?student_id=22000000&hashed_document=abc")
            self.assertEqual(r.status_code, 401)
            ok = self.client.get(
                "/api/holder-link?student_id=22000000&hashed_document=abc",
                headers={"X-Admin-Token": "r3-staff-token"})
            self.assertEqual(ok.status_code, 200)
            self.assertTrue(ok.json()["token"])
        finally:
            cfg.ADMIN_TOKEN = old

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
        chain_service.chain_info()
        # the ISSUE block should be signed by the active signer
        from app import blockchain_util
        block = blockchain_util.load_block(str(chain_service.CHAIN_DIR), res.json()["height"])
        ds_fp = block["DataSignatureInfo"][0]["DSsha256fgpt"]
        self.assertEqual(ds_fp, fp)

    # ---- notifications (U12 R4: queued, recipient is NOTIFY_TO) ----
    def test_request_address_is_ignored(self):
        res = self._issue_doc(self._doc_with_sid("99000011"),
                              email="student@example.com")
        note = res.json()["notification"]
        self.assertEqual(note["status"], "queued")
        self.assertNotEqual(note["to"], "student@example.com",
                            "a request body must not choose the recipient")
        self.assertIn("ignored", note["detail"])

    def test_queue_is_drained_by_the_worker(self):
        from app import notifier
        res = self._issue_doc(self._doc_with_sid("99000012"),
                              email="b@example.com")
        self.assertEqual(res.json()["notification"]["status"], "queued")
        drained = notifier.drain()
        self.assertGreaterEqual(drained, 1)
        rows = notifier.recent_notifications(5)
        self.assertTrue(rows)
        self.assertNotIn("b@example.com",
                         {str(r.get("to")) for r in rows},
                         "no request-supplied address may be used as a recipient")

    def test_same_credential_is_not_notified_twice(self):
        from app import notifier
        doc = self._doc_with_sid("99000013")
        first = self._issue_doc(doc)
        self.assertEqual(first.json()["notification"]["status"], "queued")
        second = self._issue_doc(doc)
        self.assertEqual(second.json()["notification"]["status"], "duplicate")
        notifier.drain()

    def test_notifications_list(self):
        from app import notifier
        self._issue_doc(self._doc_with_sid("99000014"), email="a@example.com")
        notifier.drain()
        r = self.client.get("/api/notifications")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["notifications"])

    # ---- persistence of the public log ----
    def test_public_log_persists_across_instances(self):
        h = self.client.get("/api/demo/credentials").json()["diploma"]["hashed_document"]
        self.client.get(f"/api/verify/{h}")
        log_path = public_log._log_path()
        # The jsonl file is an implementation detail of the JSON backend; under
        # STORAGE_BACKEND=sqlite the same records live in the log_entries table.
        from app import config as cfg
        if (cfg.STORAGE_BACKEND or "json").lower() == "json":
            self.assertTrue(log_path.exists())
        # a fresh instance must reload from durable storage
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
