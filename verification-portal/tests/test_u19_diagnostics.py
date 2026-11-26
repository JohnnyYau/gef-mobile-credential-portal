"""U19 — a readable diagnostics endpoint, and a PDF that admits a broken chain.

Two gaps left by U15/U16's incident handling:

* ``/healthz`` said ``config: {fatal: 0, warnings: 1}`` and nowhere to read the
  one warning; diagnosing it meant grepping the startup checks. Counts stay
  public, the text moves to a staff-only endpoint.
* A PDF is the artefact people keep. When the chain has a bad block, every
  verdict reads INVALID — but the report PDF still printed as a clean report,
  with no trace of the reason. (U14 already paints revocation for the same
  reason: a static file cannot be fixed later, so it must carry the fact.)
"""

import io
import unittest
from unittest import mock

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u19-",
    ADMIN_TOKEN="u19-admin-token",
    CAPABILITY_SECRET="u19-capability-secret",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import chain_service  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _pdf_text(content):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


class DiagnosticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls.h = {"X-Admin-Token": "u19-admin-token"}
        cls._saved_admin = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_ADMIN_MAX = 100000
        cls.hash = chain_service.hash_of(chain_service.SAMPLE_DIPLOMA)
        raw = chain_service.CHAIN_DIR / "rawjsondocs" / f"{cls.hash}.json"
        if not raw.exists():
            cls.hash = chain_service.issue(chain_service.SAMPLE_DIPLOMA)["hashed_document"]

    @classmethod
    def tearDownClass(cls):
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admin

    # ---- the readable side of /healthz --------------------------------
    def test_diagnostics_requires_staff(self):
        self.assertEqual(self.client.get("/api/diagnostics").status_code, 401)

    def test_diagnostics_exposes_the_config_messages(self):
        res = self.client.get("/api/diagnostics", headers=self.h)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertIsInstance(data["config"]["warnings"], list)
        self.assertIsInstance(data["config"]["fatal"], list)
        self.assertIn("integrity", data["chain"])
        self.assertIsInstance(data["chain"]["integrity"]["ok"], bool)
        for signer in data["chain"]["signers"]:
            self.assertIn("retired_at_height", signer)

    def test_healthz_stays_public_and_count_only(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        cfg_block = res.json()["checks"]["config"]
        self.assertIsInstance(cfg_block["warnings"], int)
        self.assertNotIn("warnings_messages", cfg_block)

    # ---- the PDF must carry the chain's state -------------------------
    def test_a_broken_chain_is_printed_on_the_report(self):
        with mock.patch.object(main, "chain_integrity",
                               return_value={"ok": False, "bad_blocks": [12]}):
            res = self.client.get(f"/api/pdf/{self.hash}")
        self.assertEqual(res.status_code, 200, res.text)
        text = _pdf_text(res.content)
        self.assertIn("CHAIN INTEGRITY FAILED", text)
        self.assertIn("block #12", text)

    def test_a_healthy_chain_leaves_the_report_clean(self):
        with mock.patch.object(main, "chain_integrity",
                               return_value={"ok": True, "bad_blocks": []}):
            res = self.client.get(f"/api/pdf/{self.hash}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn("CHAIN INTEGRITY FAILED", _pdf_text(res.content))

    def test_the_full_credential_carries_it_too(self):
        with mock.patch.object(main, "chain_integrity",
                               return_value={"ok": False, "bad_blocks": [3, 12]}):
            res = self.client.get(f"/api/admin/pdf/{self.hash}", headers=self.h)
        self.assertEqual(res.status_code, 200, res.text)
        text = _pdf_text(res.content)
        self.assertIn("CHAIN INTEGRITY FAILED", text)
        self.assertIn("#3", text)

    # ---- the printed page needs an entry point ------------------------
    def test_the_report_carries_a_scannable_qr(self):
        """Guards the U19 finding: every PDF was silently QR-less.

        ``canvas.drawImage`` refuses a BytesIO, and the TypeError was swallowed
        by a ``except ... pass`` labelled "decorative only". Six rounds of notes
        claimed a QR was drawn; none ever was. Counting embedded images is the
        cheapest assertion that can tell the two states apart.
        """
        from pypdf import PdfReader
        res = self.client.get(f"/api/pdf/{self.hash}")
        self.assertEqual(res.status_code, 200, res.text)
        page = PdfReader(io.BytesIO(res.content)).pages[0]
        self.assertEqual(len(list(page.images)), 1, "expected exactly one QR image")

    def test_without_the_qr_module_the_url_still_prints(self):
        with mock.patch("app.pdf_diploma.qrcode", None):
            res = self.client.get(f"/api/pdf/{self.hash}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("Verify online:", _pdf_text(res.content))


if __name__ == "__main__":
    unittest.main()
