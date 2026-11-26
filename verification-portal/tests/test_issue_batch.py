"""UX round — batch issue endpoint tests.

Runs in private mode (admin available) on its own isolated chain; reloads
config + chain_service + main with a fresh CHAIN_DIR so it is
order-independent within a shared unittest process.
"""

import importlib
import os
import unittest

from fastapi.testclient import TestClient

from tests._bootstrap import isolated_chain_dir


def setUpModule():
    isolated_chain_dir(prefix="gef26-batch-")
    os.environ.pop("PUBLIC_MODE", None)
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.chain_service as cs_mod
    importlib.reload(cs_mod)
    from app import main as _m
    importlib.reload(_m)
    global app, chain_service, client
    from app import chain_service as _cs
    app = _m.app
    chain_service = _cs
    client = TestClient(app)


def tearDownModule():
    # restore the pre-existing shared chain + private mode for later modules
    os.environ.pop("PUBLIC_MODE", None)
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.chain_service as cs_mod
    importlib.reload(cs_mod)
    from app import main as _m
    importlib.reload(_m)


def _doc(surname="BATCH", given="STUDENT", degree="Bachelor of Testing",
         student_id="99000001", dob="19990101"):
    return {
        "PersonalParticulars": {"Surname": surname, "GivenNames": given,
                                "Sex": "F", "DOB": dob, "StudentID": student_id},
        "AcademicInfo": {"DegreeName": degree, "DegreeStartDate": "20220901",
                         "DegreeEndDate": "20260801", "Honour": "2ND HON",
                         "Observations": "BATCH TEST"},
        "DocumentInfo": {"DateOfIssue": "20261001",
                         "AuthorizedSignature": "REGISTRAR TEST",
                         "IssuingO": "UNIVERSITY OF UTOPIA",
                         "IssuingOU": "RECORD OFFICE",
                         "DocType": "CERTIFICATE OF DIPLOMA"},
    }


class IssueBatchTest(unittest.TestCase):

    def test_batch_valid_two_rows(self):
        r = client.post("/api/issue/batch", json={"credentials": [
            {"document": _doc(student_id="99000002")},
            {"document": _doc(student_id="99000003"), "student_email": "s@example.com"},
        ]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["summary"], {"total": 2, "ok": 2, "failed": 0})
        for res in data["results"]:
            self.assertTrue(res["ok"])
            self.assertTrue(res["hashed_document"])
            self.assertTrue(res["pdf_url"].startswith("/api/pdf/"))
            self.assertTrue(res["qr_url"].startswith("/api/qr/"))
        # both hashes now verify VALID
        for res in data["results"]:
            v = client.get(f"/api/verify/{res['hashed_document']}").json()
            self.assertEqual(v["verdict"], "VALID ON CHAIN")

    def test_batch_continues_past_bad_row(self):
        r = client.post("/api/issue/batch", json={"credentials": [
            {"document": _doc(student_id="99000004")},
            {"document": {"PersonalParticulars": {"Surname": "X"}}},  # missing sections
            {"document": "not-a-dict"},
        ]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["summary"]["total"], 3)
        self.assertEqual(data["summary"]["ok"], 1)
        self.assertEqual(data["summary"]["failed"], 2)
        ok_rows = [x for x in data["results"] if x["ok"]]
        bad_rows = [x for x in data["results"] if not x["ok"]]
        self.assertEqual(len(ok_rows), 1)
        self.assertEqual(len(bad_rows), 2)
        for bad in bad_rows:
            self.assertTrue(bad["error"])

    def test_batch_empty_422(self):
        r = client.post("/api/issue/batch", json={"credentials": []})
        self.assertEqual(r.status_code, 422)

    def test_batch_missing_field_422(self):
        r = client.post("/api/issue/batch", json={})
        self.assertEqual(r.status_code, 422)

    def test_batch_public_mode_403(self):
        os.environ["PUBLIC_MODE"] = "1"
        import app.config as cfg_mod
        importlib.reload(cfg_mod)
        from app import main as _m
        importlib.reload(_m)
        try:
            c2 = TestClient(_m.app)
            r = c2.post("/api/issue/batch", json={"credentials": [
                {"document": _doc(student_id="99000005")}]})
            self.assertEqual(r.status_code, 403)
        finally:
            os.environ["PUBLIC_MODE"] = "0"
            import app.config as cfg_mod2
            importlib.reload(cfg_mod2)
            from app import main as _m2
            importlib.reload(_m2)


if __name__ == "__main__":
    unittest.main()
