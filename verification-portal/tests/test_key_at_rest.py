"""Batch U10 — signer private key at rest.

Background: every demo deployment so far kept the issuer key as a plaintext
PKCS#8 PEM under ``<chain>/keys/``. Anyone who could read the file could sign
credentials that verify. U10 makes encryption opt-in via
``GEF_KEY_PASSPHRASE`` without changing any public signature.

The cases below pin the four decisions that matter:

* passphrase set  → newly generated keys are written encrypted;
* passphrase set  → an existing plaintext key is re-encrypted on first load
  (migration, not a manual step);
* wrong passphrase → a loud, typed failure and **no** replacement key (a new
  key would orphan every block already signed);
* no passphrase    → the historical plaintext behaviour, unchanged, plus a
  boot-time warning that says so.
"""

import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import blockchain_util, chain_core, crypto_util, startup  # noqa: E402
from app import config as cfg  # noqa: E402
from app.errors import SignerUnavailableError  # noqa: E402

PASSPHRASE = "u10-test-passphrase"


class KeyAtRestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gef26-u10-"))
        self._orig_chain = chain_core.CHAIN_DIR
        self._orig_pass = cfg.SIGNER_KEY_PASSPHRASE
        chain_core.CHAIN_DIR = self.tmp / "chain"
        blockchain_util.invalidate_caches()
        cfg.SIGNER_KEY_PASSPHRASE = ""
        self._orig_algo = chain_core.SIGNER_ALGO
        chain_core.SIGNER_ALGO = "ec.SECP256R1"   # fast; mechanism is algo-agnostic

    def tearDown(self):
        chain_core.CHAIN_DIR = self._orig_chain
        cfg.SIGNER_KEY_PASSPHRASE = self._orig_pass
        chain_core.SIGNER_ALGO = self._orig_algo
        blockchain_util.invalidate_caches()
        for path in sorted(self.tmp.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        self.tmp.rmdir()

    def _keys(self) -> list[Path]:
        keys_dir = chain_core.CHAIN_DIR / "keys"
        return sorted(keys_dir.glob("*.priv.pem"))

    def test_plaintext_by_default(self):
        chain_core.ensure_chain()
        [key] = self._keys()
        self.assertNotIn(b"ENCRYPTED PRIVATE KEY", key.read_bytes())

    def test_passphrase_encrypts_a_new_key(self):
        cfg.SIGNER_KEY_PASSPHRASE = PASSPHRASE
        chain_core.ensure_chain()
        [key] = self._keys()
        self.assertIn(b"ENCRYPTED PRIVATE KEY", key.read_bytes())
        algo, priv = chain_core._load_signer()
        self.assertEqual(algo, "ec.SECP256R1")
        self.assertIsNotNone(priv)

    def test_existing_plaintext_key_is_re_encrypted_on_first_load(self):
        chain_core.ensure_chain()                    # seeded plaintext
        [key] = self._keys()
        before = crypto_util.fetch_privkey(str(key), None)
        cfg.SIGNER_KEY_PASSPHRASE = PASSPHRASE      # operator turns encryption on
        _, after = chain_core._load_signer()
        self.assertIn(b"ENCRYPTED PRIVATE KEY", key.read_bytes())
        # same key material, not a replacement
        self.assertEqual(before.private_numbers().private_value,
                         after.private_numbers().private_value)
        # and the encrypted file really needs the passphrase
        with self.assertRaises(TypeError):
            crypto_util.fetch_privkey(str(key), None)

    def test_wrong_passphrase_fails_loudly_and_keeps_the_key(self):
        cfg.SIGNER_KEY_PASSPHRASE = PASSPHRASE
        chain_core.ensure_chain()
        [key] = self._keys()
        height_before = blockchain_util.chain_params(
            str(chain_core.CHAIN_DIR))["last_block_height"]
        cfg.SIGNER_KEY_PASSPHRASE = "wrong-passphrase"
        with self.assertRaises(SignerUnavailableError) as ctx:
            chain_core._load_signer()
        self.assertIn("GEF_KEY_PASSPHRASE", str(ctx.exception))
        self.assertEqual(len(self._keys()), 1, "no replacement key may appear")
        self.assertEqual(blockchain_util.chain_params(
            str(chain_core.CHAIN_DIR))["last_block_height"], height_before)

    def test_correct_passphrase_signs_normally_after_migration(self):
        chain_core.ensure_chain()
        cfg.SIGNER_KEY_PASSPHRASE = PASSPHRASE
        algo, priv = chain_core._load_signer()
        payload = blockchain_util.issue_payload(chain_core.SAMPLE_DIPLOMA)
        blockchain_util.append_block(str(chain_core.CHAIN_DIR), payload,
                                     [(algo, priv)])
        status = blockchain_util.fetch_status(
            str(chain_core.CHAIN_DIR), payload["HashedDocument"])
        self.assertTrue(status["issued"])

    def test_issue_endpoint_shape_is_unchanged_with_a_passphrase(self):
        # The issue path the endpoint calls (issuance_service) must behave
        # identically whether or not the key is encrypted.
        from app import issuance_service
        cfg.SIGNER_KEY_PASSPHRASE = PASSPHRASE
        issuance_service.CHAIN_DIR = chain_core.CHAIN_DIR   # follow the tmp chain
        chain_core.ensure_chain()
        plain = chain_core.SAMPLE_DIPLOMA
        doc = {k: dict(v) if isinstance(v, dict) else v for k, v in plain.items()}
        doc["PersonalParticulars"]["StudentID"] = "88000001"
        result = issuance_service.issue(doc)
        self.assertIn("hashed_document", result)
        status = blockchain_util.fetch_status(
            str(chain_core.CHAIN_DIR), result["hashed_document"])
        self.assertTrue(status["issued"])


class StartupWarningsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gef26-u10w-"))
        self._orig_chain = cfg.CHAIN_DIR
        self._orig_pass = cfg.SIGNER_KEY_PASSPHRASE
        cfg.CHAIN_DIR = self.tmp / "chain"
        (cfg.CHAIN_DIR / "keys").mkdir(parents=True)

    def tearDown(self):
        cfg.CHAIN_DIR = self._orig_chain
        cfg.SIGNER_KEY_PASSPHRASE = self._orig_pass
        for path in sorted(self.tmp.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        self.tmp.rmdir()

    def _warnings(self, passphrase):
        cfg.SIGNER_KEY_PASSPHRASE = passphrase
        return startup.validate_config(types.SimpleNamespace(
            STORAGE_BACKEND="json",
            CHAIN_DIR=str(cfg.CHAIN_DIR),
            SQLITE_PATH=str(self.tmp / "portal.sqlite3"),
            STATIC_DIR=str(Path(cfg.STATIC_DIR)),
            SESSION_BACKEND="memory",
            PUBLIC_MODE=0,
            ADMIN_TOKEN=None,
            EMAIL_ENABLED=0,
            SMTP_HOST=None,
            CHAIN_SNAPSHOT_URL=None,
            SIGNER_KEY_PASSPHRASE=passphrase,
            RATE_LIMIT_ENABLED=True,
            RATE_LIMIT_PUBLIC_MAX=120,
            RATE_LIMIT_ADMIN_MAX=30,
            ALLOWED_ORIGINS="",
            PUBLIC_BASE_URL="http://127.0.0.1:8000",
        ))["warnings"]

    def test_unencrypted_key_without_passphrase_is_reported(self):
        (cfg.CHAIN_DIR / "keys" / "signer-x.priv.pem").write_bytes(
            b"-----BEGIN PRIVATE KEY-----\nnot-real\n")
        warnings = self._warnings("")
        self.assertTrue(any("GEF_KEY_PASSPHRASE is unset" in w
                            for w in warnings), warnings)
        self.assertFalse(any("fatal" in w for w in warnings))

    def test_passphrase_with_plaintext_key_is_reported(self):
        (cfg.CHAIN_DIR / "keys" / "signer-x.priv.pem").write_bytes(
            b"-----BEGIN PRIVATE KEY-----\nnot-real\n")
        warnings = self._warnings("secret")
        self.assertTrue(any("re-encrypted on first load" in w
                            for w in warnings), warnings)

    def test_encrypted_key_and_passphrase_is_quiet(self):
        (cfg.CHAIN_DIR / "keys" / "signer-x.priv.pem").write_bytes(
            b"-----BEGIN ENCRYPTED PRIVATE KEY-----\nnot-real\n")
        warnings = self._warnings("secret")
        self.assertFalse(any("GEF_KEY_PASSPHRASE" in w for w in warnings), warnings)
        self.assertFalse(any("unencrypted" in w for w in warnings), warnings)


if __name__ == "__main__":
    unittest.main()
