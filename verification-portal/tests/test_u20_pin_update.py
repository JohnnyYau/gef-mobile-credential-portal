"""U20 — key rotation must be an explicit, audited act, not a deleted file.

U18's pin is deliberately strict: any change in the anchor's fingerprint set
fails the check. That is right for an attack and wrong for a legitimate
rotation, where the only workaround was to delete the pin — which is exactly
"reset trust silently", the behaviour the fail-closed rule exists to prevent.

``--pin-update`` turns the reset into a command with three properties:

1. it only rewrites the pin when the **list itself verifies**, so a hijacked
   anchor cannot be promoted by feeding it a broken list;
2. the old/new sets and a UTC timestamp are appended to the pin's ``history``;
3. a missing ``--expect`` is reported, because then the only thing vouching for
   the new key is the same channel that delivered it.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u20-",
    ADMIN_TOKEN="u20-admin-token",
    CAPABILITY_SECRET="u20-capability-secret",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import chain_service, statuslist  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PinUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls.revoked_hash = chain_service.issue(
            chain_service.SAMPLE_TRANSCRIPT)["hashed_document"]
        chain_service.revoke(cls.revoked_hash, "U20 sample revocation")
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

    def rotate_anchor(self, fp="de:ad:be:ef"):
        """Add a second signer to the anchor — a rotation from the pin's view."""
        rotated = json.loads(json.dumps(self.anchors))
        rotated["signers"].append({
            "name": "NEW OFFICE",
            "ds_algo": "RSA_PSS_2048",
            "sha256fgpt": fp,
            "retired_at_height": None,
            "pubkey_pem": rotated["signers"][0]["pubkey_pem"],
        })
        self.an.write_text(json.dumps(rotated), encoding="utf-8")
        return fp

    def pin_json(self):
        return json.loads(self.pin.read_text(encoding="utf-8"))

    # ---- the flag only makes sense with a pin -------------------------
    def test_pin_update_without_a_pin_is_an_argument_error(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_statuslist.py"),
             str(self.sl), str(self.an), "--pin-update"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("--pin", proc.stderr)

    # ---- without the flag, a rotation still fails (U18 stays true) -----
    def test_a_rotation_is_refused_without_the_flag(self):
        self.run_cli("--pin", str(self.pin))
        fp = self.rotate_anchor()
        code, out = self.run_cli("--pin", str(self.pin))
        self.assertEqual(code, 1, out)
        self.assertEqual(out["anchor_pin"], "mismatch")
        self.assertIn(fp, out["added_since_pin"])
        self.assertIn("--pin-update", out["reason"])

    # ---- with the flag, the rotation is recorded ----------------------
    def test_pin_update_records_the_rotation_and_audit_trail(self):
        self.run_cli("--pin", str(self.pin))
        before = self.pin_json()["sha256fgpt"]
        fp = self.rotate_anchor()
        code, out = self.run_cli("--pin", str(self.pin), "--pin-update")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["anchor_pin"], "updated")
        self.assertIn(fp, out["pin_update"]["added"])
        self.assertEqual(out["pin_update"]["removed"], [])

        written = self.pin_json()
        self.assertIn(fp, written["sha256fgpt"])
        self.assertEqual(len(written["history"]), 1)
        entry = written["history"][0]
        self.assertEqual(entry["previous"], before)
        self.assertIn(fp, entry["added"])
        self.assertIn("T", entry["at"], "history timestamp should be ISO-8601")
        self.assertIn("--pin-update", entry["tool"])

    def test_the_updated_pin_matches_on_the_next_run(self):
        self.run_cli("--pin", str(self.pin))
        self.rotate_anchor()
        self.run_cli("--pin", str(self.pin), "--pin-update")
        code, out = self.run_cli("--pin", str(self.pin))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["anchor_pin"], "matched")
        self.assertEqual(len(self.pin_json()["history"]), 1)

    def test_a_second_rotation_appends_rather_than_overwrites(self):
        self.run_cli("--pin", str(self.pin))
        self.rotate_anchor("de:ad:be:01")
        self.run_cli("--pin", str(self.pin), "--pin-update")
        self.rotate_anchor("de:ad:be:02")
        code, out = self.run_cli("--pin", str(self.pin), "--pin-update")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.pin_json()["history"]), 2)
        self.assertEqual(out["pin_update"]["history_length"], 2)

    def test_no_expect_is_reported_as_a_warning(self):
        self.run_cli("--pin", str(self.pin))
        self.rotate_anchor()
        code, out = self.run_cli("--pin", str(self.pin), "--pin-update")
        self.assertEqual(code, 0, out)
        self.assertIn("--expect", out["pin_update"]["warning"])

    def test_expect_removes_the_warning(self):
        self.run_cli("--pin", str(self.pin))
        self.rotate_anchor()
        code, out = self.run_cli("--pin", str(self.pin), "--pin-update",
                                 "--expect", self.signer_fp)
        self.assertEqual(code, 0, out)
        self.assertNotIn("warning", out["pin_update"])

    # ---- the pin is never updated from an unverified list -------------
    def test_a_broken_list_cannot_promote_a_new_anchor(self):
        self.run_cli("--pin", str(self.pin))
        before = self.pin_json()
        fp = self.rotate_anchor()
        # Tamper with the body: the signature no longer covers it.
        tampered = json.loads(json.dumps(self.status))
        tampered["counts"]["revoked"] = 99
        self.sl.write_text(json.dumps(tampered), encoding="utf-8")
        code, out = self.run_cli("--pin", str(self.pin), "--pin-update")
        self.assertEqual(code, 1, out)
        self.assertEqual(out["anchor_pin"], "mismatch")
        self.assertIn("did not verify", out["reason"])
        self.assertIn(fp, out["added_since_pin"])
        self.assertEqual(self.pin_json(), before, "pin must not move on a bad list")

    def test_a_corrupt_pin_is_not_reset_by_the_flag(self):
        self.pin.write_text("{ not json", encoding="utf-8")
        code, out = self.run_cli("--pin", str(self.pin), "--pin-update")
        self.assertEqual(code, 1, out)
        self.assertEqual(out["anchor_pin"], "unreadable")
        self.assertEqual(self.pin.read_text(encoding="utf-8"), "{ not json")

    def test_a_v1_pin_is_upgraded_in_place(self):
        self.pin.write_text(json.dumps({
            "schema": "gef26.trust-anchor.pin.v1",
            "sha256fgpt": sorted(s["sha256fgpt"] for s in self.anchors["signers"]),
        }), encoding="utf-8")
        code, out = self.run_cli("--pin", str(self.pin))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["anchor_pin"], "matched")
        self.rotate_anchor()
        code, out = self.run_cli("--pin", str(self.pin), "--pin-update")
        self.assertEqual(code, 0, out)
        written = self.pin_json()
        self.assertEqual(written["schema"], "gef26.trust-anchor.pin.v2")
        self.assertEqual(len(written["history"]), 1)

    def test_the_write_leaves_no_temporary_file(self):
        self.run_cli("--pin", str(self.pin))
        self.rotate_anchor()
        self.run_cli("--pin", str(self.pin), "--pin-update")
        leftovers = sorted(p.name for p in self.dir.iterdir() if p.name.endswith(".tmp"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
