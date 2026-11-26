"""API tests for the credential verification portal (Week 1)."""

import json
import shutil
import unittest

from tests._bootstrap import isolated_chain_dir

# Use an isolated chain for tests (must be set before importing the app).
_TMP = isolated_chain_dir(prefix="portal-test-")

from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SAMPLE_DIPLOMA = {
    "PersonalParticulars": {
        "Surname": "CHAN", "GivenNames": "TAI MAN", "Sex": "M",
        "DOB": "19880808", "StudentID": "22000000",
    },
    "AcademicInfo": {
        "DegreeName": "Bachelor of Engineering / Electronic and Electrical Engineering",
        "DegreeStartDate": "20220815", "DegreeEndDate": "20260801",
        "Honour": "1ST HON", "Observations": "NO OFFICIAL OBSERVATIONS",
    },
    "DocumentInfo": {
        "DateOfIssue": "20260901", "AuthorizedSignature": "PRESIDENT Prof. QUO, Vadis",
        "IssuingO": "UNIVERSITY OF UTOPIA", "IssuingOU": "DEPT OF EE",
        "DocType": "CERTIFICATE OF DIPLOMA",
    },
}


class PortalApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)

    def test_healthz_ok(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["content_hash_algo"], "sha3_512")
        self.assertGreaterEqual(data["height"], 2)  # genesis + 2 seeded samples

    def test_index_served(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Credential Verification Portal", res.text)

    def test_demo_credentials_hashes_exist_on_chain(self):
        res = self.client.get("/api/demo/credentials")
        self.assertEqual(res.status_code, 200)
        for kind, entry in res.json().items():
            h = entry["hashed_document"]
            st = self.client.get(f"/api/status/{h}").json()
            self.assertTrue(st["issued"], kind)

    def test_verify_genuine_document(self):
        res = self.client.post("/api/verify/document",
                               json={"document": SAMPLE_DIPLOMA})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["verdict"], "VALID")
        for check in ("chain_integrity", "signer_trusted", "on_chain_record",
                      "hash_match", "signature_valid", "not_revoked"):
            self.assertTrue(data[check], check)

    def test_verify_tampered_document(self):
        forged = json.loads(json.dumps(SAMPLE_DIPLOMA))
        forged["AcademicInfo"]["DegreeName"] = "MSc Computer Science"
        data = self.client.post("/api/verify/document",
                                json={"document": forged}).json()
        self.assertEqual(data["verdict"], "INVALID")
        self.assertFalse(data["hash_match"])

    def test_verify_document_missing_sections(self):
        res = self.client.post("/api/verify/document",
                               json={"document": {"Foo": "bar"}})
        self.assertEqual(res.status_code, 422)

    def test_hash_verify_valid_on_chain(self):
        h = self.client.get("/api/demo/credentials").json()["diploma"]["hashed_document"]
        data = self.client.get(f"/api/verify/{h}").json()
        self.assertEqual(data["verdict"], "VALID ON CHAIN")
        self.assertIsNone(data["hash_match"])
        self.assertTrue(data["chain_integrity"] and data["signer_trusted"]
                        and data["signature_valid"] and data["not_revoked"])

    def test_hash_verify_unknown(self):
        fake = "A" * 86
        data = self.client.get(f"/api/verify/{fake}").json()
        self.assertEqual(data["verdict"], "NOT FOUND")

    def test_status_lifecycle(self):
        h = self.client.get("/api/demo/credentials").json()["diploma"]["hashed_document"]
        st = self.client.get(f"/api/status/{h}").json()
        self.assertTrue(st["issued"])
        self.assertEqual(len(st["issue_heights"]), 1)

    def test_issue_then_verify_then_revoke(self):
        new_doc = json.loads(json.dumps(SAMPLE_DIPLOMA))
        new_doc["PersonalParticulars"]["StudentID"] = "12345678"
        res = self.client.post("/api/issue", json={"document": new_doc})
        self.assertEqual(res.status_code, 200)
        h = res.json()["hashed_document"]

        data = self.client.post("/api/verify/document",
                                json={"document": new_doc}).json()
        self.assertEqual(data["verdict"], "VALID")

        rev = self.client.post("/api/revoke", json={"hashed_document": h})
        self.assertEqual(rev.status_code, 200)

        data = self.client.post("/api/verify/document",
                                json={"document": new_doc}).json()
        self.assertEqual(data["verdict"], "REVOKED")
        self.assertFalse(data["not_revoked"])

        hdata = self.client.get(f"/api/verify/{h}").json()
        self.assertEqual(hdata["verdict"], "REVOKED")

    def test_issue_missing_sections_422(self):
        res = self.client.post("/api/issue", json={"document": {"X": 1}})
        self.assertEqual(res.status_code, 422)

    def test_revoke_requires_hash_or_document(self):
        res = self.client.post("/api/revoke", json={})
        self.assertEqual(res.status_code, 422)

    def test_verify_bad_hash_format_422(self):
        for bad in ("short", "has spaces!", "a=b"):
            res = self.client.get(f"/api/verify/{bad}")
            self.assertEqual(res.status_code, 422, bad)

    def test_upload_json_file(self):
        files = {"file": ("credential.json",
                          json.dumps(SAMPLE_DIPLOMA).encode("utf-8"),
                          "application/json")}
        res = self.client.post("/api/verify/document", files=files)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["verdict"], "VALID")

    def test_upload_pdf_rejected_clearly(self):
        files = {"file": ("diploma.pdf", b"%PDF-1.4 fake", "application/pdf")}
        res = self.client.post("/api/verify/document", files=files)
        self.assertEqual(res.status_code, 422)
        self.assertIn("PDF", res.json()["detail"])

    def test_upload_oversize_413(self):
        big = json.dumps({"document": {"pad": "x" * (6 * 1024 * 1024)}})
        files = {"file": ("big.json", big.encode("utf-8"), "application/json")}
        res = self.client.post("/api/verify/document", files=files)
        self.assertEqual(res.status_code, 413)


if __name__ == "__main__":
    unittest.main()
