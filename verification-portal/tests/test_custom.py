"""Round 10 tests: self-service credential maker (build + issue + sync files).

Uses an isolated throwaway chain and a throwaway CUSTOM_OUTPUT_DIR so the
generated PDF/JSON land in a temp folder, never in the user's project dir.
"""

import json
import os
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="portal-custom-test-")
os.environ["CHAIN_DIR"] = os.path.join(_TMP, "test-chain")
os.environ["CUSTOM_OUTPUT_DIR"] = os.path.join(_TMP, "custom-out")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app import chain_service, custom_service  # noqa: E402


class CustomTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def _fields(self, **over):
        base = {
            "surname": "CHAN",
            "given_names": "TAI MAN",
            "student_id": "99009988",
            "dob": "1988-08-08",
            "sex": "M",
            "degree": "Bachelor of Culinary Arts",
            "degree_start": "20220901",
            "degree_end": "20260801",
            "honour": "First Class Honours",
            "observations": "",
            "issuer": "UNIVERSITY OF UTOPIA",
            "issuer_unit": "RECORD OFFICE",
        }
        base.update(over)
        return base

    def test_build_document_normalizes_fields(self):
        doc = custom_service.build_document(self._fields())
        pp = doc["PersonalParticulars"]
        ai = doc["AcademicInfo"]
        di = doc["DocumentInfo"]
        self.assertEqual(pp["Surname"], "CHAN")
        self.assertEqual(pp["StudentID"], "99009988")
        self.assertEqual(pp["DOB"], "19880808")          # dashes stripped
        self.assertEqual(ai["DegreeName"], "Bachelor of Culinary Arts")
        self.assertEqual(ai["Honour"], "First Class Honours")
        self.assertEqual(di["DocType"], "CERTIFICATE OF DIPLOMA")
        self.assertEqual(di["IssuingO"], "UNIVERSITY OF UTOPIA")

    def test_build_document_requires_name_student_degree(self):
        with self.assertRaises(ValueError):
            custom_service.build_document({"student_id": "1", "degree": "X"})
        with self.assertRaises(ValueError):
            custom_service.build_document({"surname": "CHAN", "degree": "X"})
        with self.assertRaises(ValueError):
            custom_service.build_document({"surname": "CHAN",
                                           "student_id": "1"})

    def test_build_outputs_issue_saves_files_and_verifies(self):
        res = custom_service.build_outputs(
            self._fields(given_names="烧鸡"), "http://test", issue=True)
        self.assertTrue(res["on_chain"])
        self.assertIsNotNone(res["height"])
        self.assertTrue(res["file_id"])
        pdf_path = os.path.join(res["output_dir"], res["file_id"] + ".pdf")
        json_path = os.path.join(res["output_dir"], res["file_id"] + ".json")
        self.assertTrue(os.path.isfile(pdf_path))
        self.assertTrue(os.path.isfile(json_path))
        # the JSON saved matches the issued document
        saved = json.load(open(json_path, encoding="utf-8"))
        self.assertEqual(saved["PersonalParticulars"]["Surname"], "CHAN")
        # the PDF embeds the JSON -> upload/extract -> verify VALID
        raw = open(pdf_path, "rb").read()
        extracted = main.pdf_extractor.extract_from_pdf(raw)
        self.assertEqual(extracted["mode"], "embedded_payload")
        self.assertEqual(
            extracted["document"]["PersonalParticulars"]["GivenNames"], "烧鸡")
        verdict = chain_service.verify_document(extracted["document"])
        self.assertEqual(verdict["verdict"], "VALID")

    def test_build_outputs_draft_off_chain(self):
        res = custom_service.build_outputs(
            self._fields(student_id="99007766"), "http://test", issue=False)
        self.assertFalse(res["on_chain"])
        self.assertIn("尚未上链", res["note"])
        # draft PDF still round-trips (embedding works)
        pdf_path = os.path.join(res["output_dir"], res["file_id"] + ".pdf")
        raw = open(pdf_path, "rb").read()
        extracted = main.pdf_extractor.extract_from_pdf(raw)
        self.assertEqual(extracted["mode"], "embedded_payload")

    def test_api_build_issue_endpoint(self):
        r = self.client.post("/api/custom/build",
                             json=self._fields(student_id="99006655"))
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data["on_chain"])
        self.assertIn("/api/custom/file/", data["pdf_url"])
        # file is actually servable
        fr = self.client.get(data["pdf_url"])
        self.assertEqual(fr.status_code, 200)
        self.assertEqual(fr.headers["content-type"], "application/pdf")
        jr = self.client.get(data["json_url"])
        self.assertEqual(jr.status_code, 200)
        self.assertEqual(jr.headers["content-type"], "application/json")

    def test_api_build_draft_endpoint(self):
        r = self.client.post("/api/custom/build",
                             json=self._fields(student_id="99005544", issue=False))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["on_chain"])

    def test_api_build_missing_fields_422(self):
        r = self.client.post("/api/custom/build", json={"surname": "CHAN"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("Student ID", r.json()["detail"])

    def test_api_list_and_file_safety(self):
        self.client.post("/api/custom/build",
                         json=self._fields(student_id="99004433"))
        r = self.client.get("/api/custom/list")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()["files"]), 1)
        # path traversal is rejected
        bad = self.client.get("/api/custom/file/..%2f..%2fconfig/pdf")
        self.assertIn(bad.status_code, (404, 422))
        # unknown kind is 404
        nf = self.client.get("/api/custom/file/abc123/nope")
        self.assertEqual(nf.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
