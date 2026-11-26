"""U14 console-hygiene regression.

U13 separated *entries* (who may open the console) but left three habits that
only show up in use:

    session cap      a forgotten tab keeps a role logged in forever
    sign out         closing one tab leaves the other devices signed in
    login form       unlimited guesses against a value that never rotates
    revoked PDF      a PDF issued before revocation keeps printing as valid
    holder link      a 30-day link dies with no way to renew short of asking
"""

import copy
import io
import time
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u14-test-",
    ADMIN_TOKEN="u14-admin-token",
    ISSUER_TOKEN="u14-issuer-token",
    CAPABILITY_SECRET="u14-capability-secret",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import authz, capability, chain_service  # noqa: E402
from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402

LOGIN_CLIENT = "testclient"   # what TestClient reports as request.client.host


class U14ConsoleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls.h = {"X-Admin-Token": "u14-admin-token"}
        cls._saved_admin = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_ADMIN_MAX = 100000

    @classmethod
    def tearDownClass(cls):
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admin
        authz.clear_login_failures(LOGIN_CLIENT)

    def setUp(self):
        authz.clear_login_failures(LOGIN_CLIENT)
        self.client.cookies.clear()

    # ---- helpers -------------------------------------------------------
    def _doc(self, sid):
        doc = copy.deepcopy(SAMPLE_DIPLOMA)
        doc["PersonalParticulars"]["StudentID"] = sid
        return doc

    def _issue(self, sid="24000000"):
        res = self.client.post("/api/issue", json={"document": self._doc(sid)},
                               headers=self.h)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _pdf_text(self, raw):
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(p.extract_text() or "" for p in reader.pages)

    def _sessions_of(self, role):
        return [sid for sid, e in authz._staff_sessions.items()
                if (e or {}).get("role") == role]

    # ---- F6: session cap ------------------------------------------------
    def test_a_role_keeps_at_most_three_sessions(self):
        for _ in range(6):
            authz.create_staff_session(authz.ADMIN)
        self.assertLessEqual(len(self._sessions_of(authz.ADMIN)),
                             authz.STAFF_SESSIONS_PER_ROLE)

    def test_eviction_takes_the_oldest_session_not_the_newest(self):
        start = [authz.create_staff_session(authz.ADMIN)
                 for _ in range(authz.STAFF_SESSIONS_PER_ROLE)]
        newest = authz.create_staff_session(authz.ADMIN)
        self.assertIsNone(authz.read_staff_session(start[0]))
        self.assertEqual(authz.read_staff_session(newest), authz.ADMIN)

    def test_one_role_evicting_does_not_touch_the_other(self):
        authz.drop_staff_sessions(authz.ADMIN)
        authz.drop_staff_sessions(authz.ISSUER)
        issuer_ids = [authz.create_staff_session(authz.ISSUER) for _ in range(2)]
        for _ in range(5):
            authz.create_staff_session(authz.ADMIN)
        for sid in issuer_ids:
            self.assertEqual(authz.read_staff_session(sid), authz.ISSUER)

    # ---- F6: sign out everywhere ---------------------------------------
    def test_logout_all_drops_every_session_of_the_callers_role_only(self):
        admin_ids = [authz.create_staff_session(authz.ADMIN) for _ in range(2)]
        issuer_id = authz.create_staff_session(authz.ISSUER)
        self.client.cookies.set(authz.STAFF_COOKIE, admin_ids[0])
        res = self.client.post("/staff/logout/all")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["role"], authz.ADMIN)
        self.assertGreaterEqual(res.json()["dropped"], 2)
        for sid in admin_ids:
            self.assertIsNone(authz.read_staff_session(sid))
        self.assertEqual(authz.read_staff_session(issuer_id), authz.ISSUER)

    def test_logout_all_without_a_session_is_401(self):
        self.assertEqual(self.client.post("/staff/logout/all").status_code, 401)

    # ---- F6: login throttle --------------------------------------------
    def test_login_form_locks_after_five_wrong_tokens(self):
        for _ in range(authz.LOGIN_FAIL_MAX):
            res = self.client.post("/staff/login", json={"token": "wrong"})
            self.assertEqual(res.status_code, 401)
        blocked = self.client.post("/staff/login", json={"token": "wrong"})
        self.assertEqual(blocked.status_code, 429)
        self.assertTrue(blocked.headers.get("retry-after"))
        # the brake is applied before the token is read: a correct token is
        # also refused while the window is full
        self.assertEqual(
            self.client.post("/staff/login",
                             json={"token": "u14-admin-token"}).status_code, 429)

    def test_a_successful_sign_in_clears_the_failure_counter(self):
        for _ in range(authz.LOGIN_FAIL_MAX - 1):
            self.client.post("/staff/login", json={"token": "wrong"})
        ok = self.client.post("/staff/login", json={"token": "u14-admin-token"})
        self.assertEqual(ok.status_code, 200)
        again = self.client.post("/staff/login", json={"token": "wrong"})
        self.assertEqual(again.status_code, 401)   # counter restarted, not 429

    # ---- revoked PDF band ----------------------------------------------
    def test_pdf_gains_a_revoke_band_only_after_revocation(self):
        hashed = self._issue("24000001")["hashed_document"]
        before = self._pdf_text(
            self.client.get(f"/api/admin/pdf/{hashed}", headers=self.h).content)
        self.assertNotIn("REVOKED ON CHAIN", before)
        rev = self.client.post("/api/revoke", headers=self.h,
                               json={"hashed_document": hashed,
                                     "reason": "u14 band check"})
        self.assertEqual(rev.status_code, 200, rev.text)
        after = self._pdf_text(
            self.client.get(f"/api/admin/pdf/{hashed}", headers=self.h).content)
        self.assertIn("REVOKED ON CHAIN", after)
        self.assertIn("u14 band check", after)

    def test_the_band_survives_on_the_public_report_too(self):
        hashed = self._issue("24000002")["hashed_document"]
        self.client.post("/api/revoke", headers=self.h,
                         json={"hashed_document": hashed, "reason": "public band"})
        text = self._pdf_text(self.client.get(f"/api/pdf/{hashed}").content)
        self.assertIn("REVOKED ON CHAIN", text)

    # ---- holder link renewal -------------------------------------------
    def test_renewal_is_refused_while_the_link_is_still_young(self):
        hashed = self._issue("24000003")["hashed_document"]
        fresh = capability.mint("24000003", hashed)      # full 30-day TTL
        res = self.client.post(f"/api/me/{fresh}/renew")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Renewal opens in the last 7 days", res.json()["detail"])

    def test_renewal_in_the_last_week_returns_a_working_link(self):
        hashed = self._issue("24000004")["hashed_document"]
        near = capability.mint("24000004", hashed, ttl=6 * 86400)
        res = self.client.post(f"/api/me/{near}/renew")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertGreater(body["expires_at"], body["previous_expires_at"])
        self.assertTrue(body["path"].startswith("/me/"))
        page = self.client.get(body["path"])
        self.assertEqual(page.status_code, 200)
        api = self.client.get(f"/api/me/{body['capability']}")
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json()["credentials"][0]["hashed_document"], hashed)

    def test_renewal_for_a_link_whose_record_is_gone_is_404(self):
        hashed = self._issue("24000005")["hashed_document"]
        gone = capability.mint("24999999", hashed, ttl=6 * 86400)
        self.assertEqual(self.client.post(f"/api/me/{gone}/renew").status_code, 404)


if __name__ == "__main__":
    unittest.main()
