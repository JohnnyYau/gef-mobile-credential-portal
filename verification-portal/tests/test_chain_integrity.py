"""U4.3 chain integrity tests: five damage classes + signed snapshot manifest.

Each damage case must be *reported* (``ok=False`` with a reason), never raised
out of the verifier — a corrupted chain is data a portal renders, not an
exception that takes the page down.

Build in a throwaway chain dir; the demo chain is never touched.
"""

import json
import os
import shutil
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(prefix="portal-chain-integrity-")

from app import blockchain_util as bc  # noqa: E402
from app import crypto_util  # noqa: E402
from app.config import CHAIN_DIR  # noqa: E402


class ChainIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chain = str(CHAIN_DIR)
        cls.tmp = _TMP

    def setUp(self):
        # Fresh chain per test: damage is destructive by nature.
        if os.path.exists(self.chain):
            shutil.rmtree(self.chain)
        bc.init_block(self.chain, chain_name="Integrity Test Chain")
        self.priv, self.pub = crypto_util.gen_dskey("ec.SECP256R1")
        _, sha256 = crypto_util.getfgpt(self.pub)
        from app.chain_core import _signer_priv_path
        _signer_priv_path(sha256).parent.mkdir(parents=True, exist_ok=True)
        crypto_util.save_privkey(self.priv, "ec.SECP256R1",
                                 str(_signer_priv_path(sha256)), None)
        bc.register_signer(self.chain, "Integrity Signer", self.pub,
                          "ec.SECP256R1")
        self.fgpt = sha256
        self.payload = {"DocumentInfo": {"DocType": "diploma"},
                        "HolderInfo": {"Surname": "Chan"}}
        self.block = bc.append_block(self.chain, self.payload,
                                     [("ec.SECP256R1", self.priv)])

    # -- baseline ------------------------------------------------------------

    def test_clean_chain_verifies(self):
        ok, report = bc.verify_chain(self.chain)
        self.assertTrue(ok, report)

    def test_new_blocks_carry_schema_version(self):
        self.assertEqual(self.block.get("schemaVersion"),
                         bc.BLOCK_SCHEMA_VERSION)
        genesis = bc.load_block(self.chain, 0)
        self.assertEqual(genesis.get("schemaVersion"), bc.BLOCK_SCHEMA_VERSION)

    def test_chain_params_expose_identity(self):
        params = bc.chain_params(self.chain)
        self.assertTrue(params["chain_id"].startswith("cid-"))
        self.assertEqual(params["params_version"], 1)
        self.assertEqual(params["last_block_height"], self.block["height"])

    # -- damage 1: missing block --------------------------------------------

    def test_missing_block_is_reported(self):
        os.remove(bc._block_path(self.chain, self.block["height"]))
        ok, report = bc.verify_chain(self.chain)
        self.assertFalse(ok)
        self.assertTrue(any(not r.get("ok") for r in report))

    # -- damage 2: malformed JSON -------------------------------------------

    def test_malformed_json_is_reported(self):
        with open(bc._block_path(self.chain, self.block["height"]), "w",
                  encoding="utf-8") as fh:
            fh.write("{not json at all")
        ok, report = bc.verify_chain(self.chain)
        self.assertFalse(ok)
        self.assertTrue(any(not r.get("ok") for r in report))

    # -- damage 3: broken prevHash ------------------------------------------

    def test_broken_prev_hash_is_reported(self):
        block = json.loads(json.dumps(self.block))
        block["prevHashSum"] = "A" * 80
        bc._write_block_file(self.chain, block)
        ok, _ = bc.verify_chain(self.chain)
        self.assertFalse(ok)

    # -- damage 4: fingerprint not in the registry --------------------------

    def test_untrusted_fingerprint_is_reported(self):
        block = json.loads(json.dumps(self.block))
        block["DataSignatureInfo"][0]["DSsha256fgpt"] = "de:ad:be:ef"
        bc._write_block_file(self.chain, block)
        result = bc.verify_block(self.chain, self.block["height"])
        self.assertFalse(result["ok"])
        self.assertIn("untrusted",
                      " ".join(result.get("signature_problems", [])))

    # -- damage 5: algorithm mismatch against the registry -------------------

    def test_algorithm_mismatch_is_reported(self):
        block = json.loads(json.dumps(self.block))
        block["DataSignatureInfo"][0]["DSAlgo"] = "RSA-2048"
        bc._write_block_file(self.chain, block)
        ok, _ = bc.verify_chain(self.chain)
        self.assertFalse(ok)

    # -- payload tampering (the classic case) -------------------------------

    def test_payload_tampering_is_reported(self):
        block = json.loads(json.dumps(self.block))
        block["payload"]["HolderInfo"]["Surname"] = "Lee"
        bc._write_block_file(self.chain, block)
        ok, _ = bc.verify_chain(self.chain)
        self.assertFalse(ok)

    # -- signed snapshot manifest -------------------------------------------

    def test_snapshot_manifest_is_signed_and_verifiable(self):
        from app import signer_service
        signer_service.set_active_signer(self.fgpt)
        snap = signer_service.snapshot_manifest()
        manifest = snap["manifest"]
        self.assertEqual(manifest["height"], self.block["height"])
        self.assertEqual(manifest["chain_id"],
                         bc.chain_params(self.chain)["chain_id"])
        self.assertEqual(len(manifest["signers"]), 1)
        self.assertEqual(snap["signature"]["DSsha256fgpt"], self.fgpt)
        self.assertTrue(snap["signature"]["DSignature"])
        # the recorded signature must verify against the manifest itself
        pub = crypto_util.fetch_pubkey(
            bc._signer_pub_path(self.chain, self.fgpt))
        self.assertTrue(crypto_util.verify_ds(
            manifest, snap["signature"]["DSAlgo"], pub,
            snap["signature"]["DSignature"],
            snap["signature"]["DSnonce"],
            content_hash_algo=manifest["content_hash_algo"]))

if __name__ == "__main__":
    unittest.main()
