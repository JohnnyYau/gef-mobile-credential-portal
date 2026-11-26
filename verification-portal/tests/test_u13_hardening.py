"""U13 feature-hardening regression (F1-F8).

Each assertion maps to a hole the U13 plan closed:

    F1  hash-as-bearer on /api/pdf        -> public PDF is a report, not the credential
    F2  anonymous custom/notifications    -> 401 without a staff credential
    F3  holder page with no facts         -> issued_at / height / revoke reason
    F4  role-blind console                -> /api/staff/whoami answers honestly
    F5  batch with no links               -> holder_path minted per row
    F7  silent demo-open                  -> DEMO_OPEN=0 fails closed
"""

import copy
import io
import unittest
from unittest import mock

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u13-test-",
    ADMIN_TOKEN="u13-admin-token",
    CAPABILITY_SECRET="u13-capability-secret",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import authz, chain_service, pdf_diploma  # noqa: E402
from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402


class U13HardeningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls.h = {"X-Admin-Token": "u13-admin-token"}
        cls._saved_admin = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_ADMIN_MAX = 100000

    @classmethod
    def tearDownClass(cls):
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admin

    # ---- helpers -------------------------------------------------------
    def _doc(self, sid):
        doc = copy.deepcopy(SAMPLE_DIPLOMA)
        doc["PersonalParticulars"]["StudentID"] = sid
        return doc

    def _issue(self, sid="23000000"):
        res = self.client.post("/api/issue", json={"document": self._doc(sid)},
                               headers=self.h)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _pdf_text(self, raw):
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(p.extract_text() or "" for p in reader.pages)

    # ---- F1: report vs credential --------------------------------------
    def test_public_pdf_is_a_report_not_the_credential(self):
        hashed = self._issue()["hashed_document"]
        res = self.client.get(f"/api/pdf/{hashed}")
        self.assertEqual(res.status_code, 200)
        self.assertIn('filename="verification-', res.headers["content-disposition"])
        self.assertEqual(res.headers["cache-control"], "public, max-age=3600")
        self.assertIn("withheld", self._pdf_text(res.content).lower())
        with self.assertRaises(ValueError):
            pdf_diploma.extract_credential(res.content)

    def test_public_pdf_never_carries_the_student_name(self):
        surname = SAMPLE_DIPLOMA["PersonalParticulars"]["Surname"]
        hashed = self._issue()["hashed_document"]
        text = self._pdf_text(self.client.get(f"/api/pdf/{hashed}").content)
        self.assertNotIn(surname, text)

    def test_admin_pdf_is_the_full_credential(self):
        hashed = self._issue()["hashed_document"]
        self.assertEqual(self.client.get(f"/api/admin/pdf/{hashed}").status_code, 401)
        res = self.client.get(f"/api/admin/pdf/{hashed}", headers=self.h)
        self.assertEqual(res.status_code, 200)
        self.assertIn('filename="credential-', res.headers["content-disposition"])
        self.assertEqual(res.headers["cache-control"], "no-store")
        doc = pdf_diploma.extract_credential(res.content)
        self.assertEqual(doc["PersonalParticulars"]["StudentID"], "23000000")

    def test_holder_pdf_needs_a_valid_capability(self):
        issued = self._issue("23000001")
        link = self.client.get("/api/holder-link", headers=self.h,
                               params={"student_id": "23000001",
                                       "hashed_document": issued["hashed_document"]})
        self.assertEqual(link.status_code, 200)
        cap = link.json()["token"]
        ok = self.client.get(f"/api/me/{cap}/pdf")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(len(PdfReader(io.BytesIO(ok.content)).attachments), 1)
        tampered = cap[:-1] + ("A" if cap[-1] != "A" else "B")
        self.assertEqual(self.client.get(f"/api/me/{tampered}/pdf").status_code, 404)

    # ---- F2: staff-only listings ---------------------------------------
    def test_custom_and_notifications_are_staff_only(self):
        for path in ("/api/custom/list", "/api/notifications",
                     "/api/custom/file/nope/pdf"):
            self.assertEqual(self.client.get(path).status_code, 401, path)
            self.assertEqual(self.client.get(path, headers=self.h).status_code,
                             200 if path != "/api/custom/file/nope/pdf" else 404, path)

    # ---- F3: holder page facts -----------------------------------------
    def test_holder_view_reports_issue_point_and_revoke_reason(self):
        issued = self._issue("23000002")
        link = self.client.get("/api/holder-link", headers=self.h,
                               params={"student_id": "23000002",
                                       "hashed_document": issued["hashed_document"]})
        cap = link.json()["token"]
        before = self.client.get(f"/api/me/{cap}").json()["credentials"][0]
        self.assertTrue(before["issued_height"])
        self.assertTrue(before["issued_at"])
        self.assertFalse(before["revoked"])

        revoked = self.client.post("/api/revoke", headers=self.h,
                                   json={"hashed_document": issued["hashed_document"],
                                         "reason": "u13 regression reason"})
        self.assertEqual(revoked.status_code, 200, revoked.text)
        after = self.client.get(f"/api/me/{cap}").json()["credentials"][0]
        self.assertTrue(after["revoked"])
        self.assertEqual(after["revoked_reason"], "u13 regression reason")

    # ---- F4: whoami -----------------------------------------------------
    def test_whoami_tells_the_console_which_role_it_has(self):
        anon = self.client.get("/api/staff/whoami").json()
        self.assertIsNone(anon["role"])
        self.assertFalse(anon["demo_open"])
        admin = self.client.get("/api/staff/whoami", headers=self.h).json()
        self.assertEqual(admin["role"], "admin")
        self.assertFalse(admin["demo_open"])
        bad = self.client.get("/api/staff/whoami",
                              headers={"X-Admin-Token": "nope"}).json()
        self.assertIsNone(bad["role"])

    # ---- F5: batch mints holder links -----------------------------------
    def test_batch_returns_a_holder_link_for_each_row(self):
        body = {"credentials": [{"document": self._doc("23000003")}]}
        res = self.client.post("/api/issue/batch", json=body, headers=self.h)
        row = res.json()["results"][0]
        self.assertTrue(row["ok"])
        self.assertTrue(row["holder_path"].startswith("/me/"))
        self.assertTrue(row["credential_pdf_url"].startswith("/api/admin/pdf/"))
        cap = row["holder_path"][len("/me/"):]
        seen = self.client.get(f"/api/me/{cap}").json()["credentials"][0]
        self.assertEqual(seen["hashed_document"], row["hashed_document"])

    # ---- F7: demo-open is a switch --------------------------------------
    def test_demo_open_can_be_closed(self):
        with mock.patch.object(authz, "configured_roles", return_value={}), \
                mock.patch.object(authz.cfg, "DEMO_OPEN", True):
            self.assertEqual(self.client.get("/api/custom/list").status_code, 200)
        with mock.patch.object(authz, "configured_roles", return_value={}), \
                mock.patch.object(authz.cfg, "DEMO_OPEN", False):
            res = self.client.get("/api/custom/list")
            self.assertEqual(res.status_code, 401)
            self.assertIn("DEMO_OPEN=0", res.json()["detail"])


if __name__ == "__main__":
    unittest.main()
