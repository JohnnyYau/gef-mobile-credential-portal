"""U16 signer retirement: drop a key's trust without breaking its history.

This is the protocol half of the U15 incident. That demo chain had a block
signed by a signer that had been removed from ``info.yaml``; with no public
key and no entry, the block was unverifiable and *every* verdict read INVALID. The
fix is a boundary, not a deletion: keep the key, keep the entry, record the
height after which it is no longer trusted.
"""

import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u16-test-",
    ADMIN_TOKEN="u16-admin-token",
    CAPABILITY_SECRET="u16-capability-secret",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import blockchain_util, chain_service  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class SignerRetirementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls.h = {"X-Admin-Token": "u16-admin-token"}
        cls._saved_admin = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_ADMIN_MAX = 100000
        cls.chain = str(chain_service.CHAIN_DIR)

    @classmethod
    def tearDownClass(cls):
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admin

    def setUp(self):
        """Idempotent state: a second signer exists and is the active one."""
        signers = chain_service.list_signers()
        second = next((s for s in signers["signers"] if s["name"] == "U16 SECOND"), None)
        if second is None:
            second = chain_service.add_signer("U16 SECOND", "RSA_PSS_2048")
        self.second = second
        self.first = next(s for s in signers["signers"]
                          if s["name"] != "U16 SECOND")
        if signers["active"] != second["sha256fgpt"]:
            chain_service.set_active_signer(second["sha256fgpt"])

    # ---- the point of the whole batch ---------------------------------
    def test_retiring_a_past_signer_keeps_the_chain_valid(self):
        ok_before, _ = blockchain_util.verify_chain(self.chain)
        self.assertTrue(ok_before)

        retired = chain_service.retire_signer(self.first["sha256fgpt"])
        self.assertIsInstance(retired["retired_at_height"], int)

        ok_after, rows = blockchain_util.verify_chain(self.chain)
        self.assertTrue(ok_after, [r for r in rows if not r.get("ok")])

        # The registry still holds the key: that is what lets the old blocks
        # keep verifying. Only the boundary changed.
        self.assertTrue(blockchain_util.is_trusted(self.chain,
                                                   self.first["sha256fgpt"]))
        boundary = retired["retired_at_height"]
        self.assertTrue(blockchain_util.signer_trusted_at(
            self.chain, self.first["sha256fgpt"], boundary))
        self.assertFalse(blockchain_util.signer_trusted_at(
            self.chain, self.first["sha256fgpt"], boundary + 1))

    def test_retire_uses_the_same_active_fallback_as_the_list(self):
        """A freshly seeded chain has no active-signer.json.

        ``list_signers`` then falls back to the first registered signer, and the
        live check caught retire disagreeing with it: the API showed that key as
        active while retiring it succeeded. Both must resolve the same answer.
        """
        from unittest import mock

        first_fp = chain_service.list_signers()["signers"][0]["sha256fgpt"]
        with mock.patch("app.signer_service._active_signer_fgpt", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                chain_service.retire_signer(first_fp)
        self.assertIn("active", str(ctx.exception).lower())

    def test_a_retired_signer_cannot_be_made_active_again(self):
        chain_service.retire_signer(self.first["sha256fgpt"])
        with self.assertRaises(ValueError) as ctx:
            chain_service.set_active_signer(self.first["sha256fgpt"])
        self.assertIn("retired", str(ctx.exception).lower())

    # ---- API surface ---------------------------------------------------
    def test_api_retire_is_idempotent_and_audited(self):
        fp = self.first["sha256fgpt"]
        first = self.client.post("/api/signers/retire", json={"sha256fgpt": fp},
                                 headers=self.h)
        self.assertEqual(first.status_code, 200, first.text)
        again = self.client.post("/api/signers/retire", json={"sha256fgpt": fp},
                                 headers=self.h)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(first.json()["retired_at_height"],
                         again.json()["retired_at_height"])

    def test_api_retire_refuses_the_active_signer(self):
        active = chain_service.list_signers()["active"]
        res = self.client.post("/api/signers/retire",
                               json={"sha256fgpt": active}, headers=self.h)
        self.assertEqual(res.status_code, 422, res.text)
        self.assertIn("switch to another signer", res.json()["detail"])

    def test_api_retire_rejects_an_unknown_fingerprint(self):
        res = self.client.post("/api/signers/retire",
                               json={"sha256fgpt": "00:11:22:33"}, headers=self.h)
        self.assertEqual(res.status_code, 422, res.text)
        self.assertIn("No registered signer", res.json()["detail"])

    def test_retire_requires_a_staff_credential(self):
        self.assertEqual(
            self.client.post("/api/signers/retire",
                             json={"sha256fgpt": self.first["sha256fgpt"]}
                             ).status_code, 401)


if __name__ == "__main__":
    unittest.main()
