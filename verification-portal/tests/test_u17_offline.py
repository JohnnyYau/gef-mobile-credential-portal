"""U17 — make the "cache it and answer offline" promise actually true.

The status list used to be signed with a payload that carried no nonce and
stamped ``signer`` from ``SIGNER_NAME`` in config.  So: the signature could not
be recomputed by anyone (the nonce is part of the signed message), it named the
wrong key after a rotation, and there was no way to obtain a public key. An
employer who cached the list could only trust the portal it had just cached it
from — the opposite of offline verification.

These tests check the whole loop: sign with the key that actually signed, publish
the key, verify with no portal call, and reject a tampered or post-retirement list.
"""

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u17-",
    ADMIN_TOKEN="u17-admin-token",
    CAPABILITY_SECRET="u17-capability-secret",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import chain_service, crypto_util, statuslist  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "verify_statuslist_script", ROOT / "scripts" / "verify_statuslist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineVerificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls.h = {"X-Admin-Token": "u17-admin-token"}
        cls.script = _load_script()
        # The list needs at least one revoked row; a fresh isolated chain has
        # none unless something is actually revoked.
        cls.revoked_hash = chain_service.issue(
            chain_service.SAMPLE_TRANSCRIPT)["hashed_document"]
        chain_service.revoke(cls.revoked_hash, "U17 sample revocation")
        statuslist.build(force=True)

    def _anchors(self):
        return self.client.get("/api/signers/keys").json()

    def _status(self):
        return self.client.get("/api/statuslist").json()

    def test_statuslist_verifies_with_the_published_key(self):
        status = self._status()
        self.assertEqual(status["schema"], "gef26.statuslist.v2")
        sig = status["signature"]
        self.assertTrue(sig["nonce"])
        self.assertTrue(sig["sha256fgpt"])

        anchors = self._anchors()
        result = self.script.verify(status, anchors)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["signer"]["sha256fgpt"], sig["sha256fgpt"])

    def test_keys_endpoint_publishes_usable_pem_without_a_token(self):
        anchors = self._anchors()  # deliberately no admin header
        self.assertTrue(anchors["signers"])
        chain = anchors.get("chain") or {}
        self.assertIn("height", chain)
        self.assertEqual(chain.get("content_hash_algo"), "sha3_512")
        for entry in anchors["signers"]:
            self.assertTrue(entry["pubkey_pem"].startswith("-----BEGIN PUBLIC KEY"))
            from cryptography.hazmat.primitives import serialization
            pub = serialization.load_pem_public_key(entry["pubkey_pem"].encode())
            _, fp = crypto_util.getfgpt(pub)
            self.assertEqual(fp, entry["sha256fgpt"])

    def test_the_signature_names_the_key_that_signed(self):
        """A rotation must change whose fingerprint the list carries.

        v1 wrote ``SIGNER_NAME`` from config, so after switching signers the list
        still claimed to be signed by the first one — a reader following that
        name would fetch the wrong public key.
        """
        signers = chain_service.list_signers()
        second = next((s for s in signers["signers"]
                       if s["sha256fgpt"] != signers["active"]), None) \
            or chain_service.add_signer("U17 SECOND", "RSA_PSS_2048")
        previous = chain_service.list_signers()["active"]
        try:
            chain_service.set_active_signer(second["sha256fgpt"])
            status = statuslist.build(force=True)[0]
            sig = status["signature"]
            self.assertEqual(sig["sha256fgpt"], second["sha256fgpt"])
            self.assertEqual(sig["signer"], second["name"])
            self.assertTrue(self.script.verify(status, self._anchors())["ok"])
        finally:
            chain_service.set_active_signer(previous)
            statuslist.build(force=True)

    def test_a_tampered_list_fails(self):
        status = json.loads(json.dumps(self._status()))
        self.assertTrue(status["revoked"], "need at least one revoked row")
        status["revoked"][0]["reason"] = "tampered"
        result = self.script.verify(status, self._anchors())
        self.assertFalse(result["ok"], result)
        self.assertIn("does not verify", result["reason"])

    def test_a_list_signed_after_retirement_is_rejected(self):
        status = self._status()
        anchors = json.loads(json.dumps(self._anchors()))
        sig_fp = status["signature"]["sha256fgpt"]
        entry = next(s for s in anchors["signers"] if s["sha256fgpt"] == sig_fp)
        entry["retired_at_height"] = int(status["snapshot"]["height"]) - 1
        result = self.script.verify(status, anchors)
        self.assertFalse(result["ok"], result)
        self.assertIn("retired", result["reason"])

    def test_cli_exit_codes_and_lookup(self):
        status = self._status()
        anchors = self._anchors()
        with tempfile.TemporaryDirectory() as tmp:
            sl_path = pathlib.Path(tmp) / "statuslist.json"
            keys_path = pathlib.Path(tmp) / "anchors.json"
            sl_path.write_text(json.dumps(status), encoding="utf-8")
            keys_path.write_text(json.dumps(anchors), encoding="utf-8")

            good = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_statuslist.py"),
                 str(sl_path), str(keys_path)],
                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertTrue(json.loads(good.stdout)["ok"])

            revoked_hash = status["revoked"][0]["hash"]
            lookup = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_statuslist.py"),
                 str(sl_path), str(keys_path), "--hash", revoked_hash],
                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(lookup.returncode, 0, lookup.stderr)
            self.assertTrue(json.loads(lookup.stdout)["lookup"]["revoked"])

            status["revoked"][0]["reason"] = "tampered"
            sl_path.write_text(json.dumps(status), encoding="utf-8")
            bad = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_statuslist.py"),
                 str(sl_path), str(keys_path)],
                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(bad.returncode, 1, bad.stdout)


if __name__ == "__main__":
    unittest.main()
