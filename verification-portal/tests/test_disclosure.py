"""U4.4 disclosure view tests: section redaction bound to the on-chain hash."""

import json
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(prefix="portal-disclosure-test-")

import app.main as main  # noqa: E402
from app import chain_core, chain_service, disclosure  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class DisclosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.doc = chain_core.SAMPLE_DIPLOMA
        chain_service.ensure_chain()
        issued = chain_service.issue(cls.doc)
        cls.hashed = issued["hashed_document"]
        cls.record = chain_service.on_chain_payload(cls.hashed)

    # -- view construction ---------------------------------------------------

    def test_default_hides_identity_section(self):
        view = disclosure.make_disclosure(self.doc)
        self.assertEqual(view["hidden_sections"], ["PersonalParticulars"])
        self.assertEqual(sorted(view["disclosed_sections"]),
                         ["AcademicInfo", "DocumentInfo"])
        self.assertNotIn("DOB", json.dumps(view))
        self.assertNotIn("StudentID", json.dumps(view))

    def test_credential_hash_matches_issued_hash(self):
        view = disclosure.make_disclosure(self.doc)
        self.assertEqual(view["credential_hash"], self.hashed)

    def test_hidden_section_hash_is_the_on_chain_one(self):
        view = disclosure.make_disclosure(self.doc)
        self.assertEqual(view["hidden_section_hashes"]["PersonalParticulars"],
                         self.record["HashedPersonalParticulars"])

    def test_disclosed_section_hash_matches_record(self):
        view = disclosure.make_disclosure(self.doc)
        self.assertEqual(view["section_hashes"]["AcademicInfo"],
                         self.record["HashedAcademicInfo"])

    def test_cannot_hide_every_section(self):
        with self.assertRaises(ValueError):
            disclosure.make_disclosure(self.doc, list(disclosure.SECTIONS))

    def test_unknown_section_is_rejected(self):
        with self.assertRaises(ValueError):
            disclosure.make_disclosure(self.doc, ["TranscriptInfo"])

    # -- binding -------------------------------------------------------------

    def test_view_binds_to_record(self):
        report = disclosure.check_against_record(
            disclosure.make_disclosure(self.doc), self.record)
        self.assertTrue(report["ok"], report["reasons"])
        self.assertEqual(sorted(report["bound_sections"]),
                         ["AcademicInfo", "DocumentInfo"])

    def test_edited_disclosed_field_breaks_the_binding(self):
        view = disclosure.make_disclosure(self.doc)
        view["disclosed_sections"]["AcademicInfo"]["DegreeName"] = "PhD in Nothing"
        report = disclosure.check_against_record(view, self.record)
        self.assertFalse(report["ok"])
        self.assertTrue(any("AcademicInfo" in r for r in report["reasons"]))

    def test_wrong_credential_hash_is_rejected(self):
        view = disclosure.make_disclosure(self.doc)
        view["credential_hash"] = "A" * 86
        report = disclosure.check_against_record(view, self.record)
        self.assertFalse(report["ok"])

    def test_field_hiding_is_declared_unbound(self):
        view = disclosure.make_disclosure(
            self.doc, hide_fields=["AcademicInfo.Honour"])
        self.assertIn("AcademicInfo", view["unbound_sections"])
        self.assertIsNone(view["section_hashes"]["AcademicInfo"])
        self.assertIn("AcademicInfo.Honour", view["commitments"])
        report = disclosure.check_against_record(view, self.record)
        self.assertFalse(report["ok"])

    def test_field_commitment_opens_with_value_and_salt(self):
        view = disclosure.make_disclosure(
            self.doc, hide_fields=["AcademicInfo.Honour"])
        entry = view["commitments"]["AcademicInfo.Honour"]
        self.assertEqual(
            disclosure.open_commitment("1ST HON", entry["salt"]),
            entry["commitment"])

    # -- endpoints -----------------------------------------------------------

    def test_disclose_endpoint_returns_bound_view(self):
        r = self.client.post(f"/api/disclose/{self.hashed}", json={})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["credential_hash"], self.hashed)
        self.assertEqual(body["hidden_sections"], ["PersonalParticulars"])
        self.assertNotIn("DOB", json.dumps(body))

    def test_disclose_endpoint_404_for_unknown_hash(self):
        r = self.client.post("/api/disclose/AAAAunknownHASH", json={})
        self.assertEqual(r.status_code, 404)

    def test_verify_endpoint_confirms_disclosed_sections(self):
        view = self.client.post(f"/api/disclose/{self.hashed}", json={}).json()
        r = self.client.post("/api/verify/disclosure", json=view)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body["reasons"])
        self.assertEqual(body["chain_verdict"], "VALID ON CHAIN")
        self.assertIn("zero-knowledge", body["assurance"])

    def test_verify_endpoint_rejects_tampered_view(self):
        view = self.client.post(f"/api/disclose/{self.hashed}", json={}).json()
        view["disclosed_sections"]["DocumentInfo"]["IssuingO"] = "FAKE UNI"
        body = self.client.post("/api/verify/disclosure", json=view).json()
        self.assertFalse(body["ok"])

    def test_verify_endpoint_executes_no_document_upload(self):
        """A view alone is enough: no full document is ever requested."""
        view = self.client.post(f"/api/disclose/{self.hashed}", json={}).json()
        body = self.client.post("/api/verify/disclosure", json=view).json()
        self.assertNotIn("document", body)


if __name__ == "__main__":
    unittest.main()
