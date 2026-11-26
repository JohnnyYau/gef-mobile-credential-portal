"""U18 — an anchor file you just fetched proves nothing by itself.

U17 made the status list verifiable, but both halves (list, anchors) normally
arrive from the same place. A hijacked source can hand you its own keys and a
list it signed, and the check passes: the pair is self-consistent and completely
false. Two defences:

* ``--expect`` — the fingerprint you already know out of band must be the one
  that signed.
* ``--pin`` — record the anchor's fingerprint set on first use; a later anchor
  with a different set is refused, and an unreadable pin fails closed instead of
  silently becoming "first use" again.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u18-",
    ADMIN_TOKEN="u18-admin-token",
    CAPABILITY_SECRET="u18-capability-secret",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import chain_service, statuslist  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


class AnchorPinningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls.revoked_hash = chain_service.issue(
            chain_service.SAMPLE_TRANSCRIPT)["hashed_document"]
        chain_service.revoke(cls.revoked_hash, "U18 sample revocation")
        statuslist.build(force=True)
        cls.status = cls.client.get("/api/statuslist").json()
        cls.anchors = cls.client.get("/api/signers/keys").json()
        cls.signer_fp = cls.status["signature"]["sha256fgpt"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.sl = self.dir / "statuslist.json"
        self.an = self.dir / "anchors.json"
        self.pin = self.dir / "trust-anchor.pin.json"
        self.sl.write_text(json.dumps(self.status), encoding="utf-8")
        self.an.write_text(json.dumps(self.anchors), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *extra):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_statuslist.py"),
             str(self.sl), str(self.an), *extra],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        try:
            out = json.loads(proc.stdout)
        except Exception:
            out = {"stdout": proc.stdout, "stderr": proc.stderr}
        return proc.returncode, out

    # ---- expect: trust the fingerprint you already have ----------------
    def test_expected_fingerprint_is_accepted(self):
        code, out = self.run_cli("--expect", self.signer_fp)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])

    def test_a_different_expected_fingerprint_is_refused(self):
        code, out = self.run_cli("--expect", "00:11:22:33")
        self.assertEqual(code, 1, out)
        self.assertIn("expected set", out["reason"])

    def test_expect_matches_case_insensitively(self):
        code, out = self.run_cli("--expect", self.signer_fp.upper())
        self.assertEqual(code, 0, out)

    # ---- pin: first use, then enforcement ------------------------------
    def test_pin_is_created_then_matched(self):
        code, out = self.run_cli("--pin", str(self.pin))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["anchor_pin"], "created")
        pinned = json.loads(self.pin.read_text(encoding="utf-8"))
        expected = sorted(s["sha256fgpt"] for s in self.anchors["signers"])
        self.assertEqual(pinned["sha256fgpt"], expected)

        code, out = self.run_cli("--pin", str(self.pin))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["anchor_pin"], "matched")

    def test_an_anchor_with_a_new_signer_breaks_the_pin(self):
        self.run_cli("--pin", str(self.pin))
        tampered = json.loads(json.dumps(self.anchors))
        tampered["signers"].append({
            "name": "ATTACKER",
            "ds_algo": "RSA_PSS_2048",
            "sha256fgpt": "aa:bb:cc:dd",
            "retired_at_height": None,
            "pubkey_pem": tampered["signers"][0]["pubkey_pem"],
        })
        self.an.write_text(json.dumps(tampered), encoding="utf-8")
        code, out = self.run_cli("--pin", str(self.pin))
        self.assertEqual(code, 1, out)
        self.assertEqual(out["anchor_pin"], "mismatch")
        self.assertIn("aa:bb:cc:dd", out["added_since_pin"])

    def test_a_corrupt_pin_fails_closed(self):
        """Deleting or breaking the pin must not quietly restart trust."""
        self.pin.write_text("{ not json", encoding="utf-8")
        code, out = self.run_cli("--pin", str(self.pin))
        self.assertEqual(code, 1, out)
        self.assertEqual(out["anchor_pin"], "unreadable")

    def test_an_empty_pin_list_is_unreadable(self):
        self.pin.write_text(json.dumps({"schema": "x", "sha256fgpt": []}), encoding="utf-8")
        code, out = self.run_cli("--pin", str(self.pin))
        self.assertEqual(code, 1, out)
        self.assertEqual(out["anchor_pin"], "unreadable")

    def test_pin_and_expect_work_together(self):
        code, out = self.run_cli("--pin", str(self.pin), "--expect", self.signer_fp)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["anchor_pin"], "created")
        code, out = self.run_cli("--pin", str(self.pin), "--expect", "00:11:22:33")
        self.assertEqual(code, 1, out)
        self.assertIn("expected set", out["reason"])


if __name__ == "__main__":
    unittest.main()
