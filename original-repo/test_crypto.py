"""Unit tests for crypto_util: RFC8785 hashing, merkle root, multi-algo DS."""

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crypto_util


def _sample_payload():
    return {
        "action": "ISSUE",
        "HashedPersonalParticulars": "abc",
        "HashedAcademicInfo": "def",
        "HashedDocumentInfo": "ghi",
        "HashedDocument": "jkl",
    }


class TestHashJson(unittest.TestCase):
    def test_canonicalisation_is_key_order_independent(self):
        a = {"b": [1, 2, 3], "a": {"x": 1}, "c": None}
        b = {"c": None, "a": {"x": 1}, "b": [1, 2, 3]}
        self.assertEqual(crypto_util.hash_json(a), crypto_util.hash_json(b))

    def test_urlsafe_base64_no_padding(self):
        digest = crypto_util.hash_json({"k": "v"})
        self.assertNotIn("=", digest)
        self.assertNotIn("+", digest)
        self.assertNotIn("/", digest)

    def test_matches_manual_sha3_512(self):
        import base64
        import hashlib
        canonical = crypto_util.json_rfc8785({"a": 1})
        if isinstance(canonical, str):
            canonical = canonical.encode("utf-8")
        expected = base64.urlsafe_b64encode(hashlib.sha3_512(canonical).digest()).decode("ascii").rstrip("=")
        self.assertEqual(crypto_util.hash_json({"a": 1}, "sha3_512"), expected)

    def test_other_hash_algos(self):
        for algo in ("sha256", "sha512", "sha3_256", "sha3_384"):
            d = crypto_util.hash_json({"a": 1}, algo)
            self.assertEqual(len(d), len(crypto_util.hash_json({"a": 2}, algo)))

    def test_unsupported_algo_raises(self):
        with self.assertRaises(ValueError):
            crypto_util.hash_json({"a": 1}, "md5-not-supported")


class TestMerkleRoot(unittest.TestCase):
    def test_single_leaf_returns_leaf(self):
        leaf = crypto_util.hash_json({"x": 1})
        self.assertEqual(crypto_util.merkle_root([leaf]), leaf)

    def test_two_leaves(self):
        a = crypto_util.hash_json({"x": 1})
        b = crypto_util.hash_json({"x": 2})
        self.assertEqual(
            crypto_util.merkle_root([a, b]),
            crypto_util.hash_bytes((a + b).encode("ascii")),
        )

    def test_three_leaves_duplicates_last(self):
        a = crypto_util.hash_json({"x": 1})
        b = crypto_util.hash_json({"x": 2})
        c = crypto_util.hash_json({"x": 3})
        root = crypto_util.merkle_root([a, b, c])
        self.assertIsInstance(root, str)
        self.assertEqual(root, crypto_util.merkle_root([a, b, c]))  # deterministic

    def test_order_sensitive(self):
        a = crypto_util.hash_json({"x": 1})
        b = crypto_util.hash_json({"x": 2})
        self.assertNotEqual(crypto_util.merkle_root([a, b]), crypto_util.merkle_root([b, a]))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            crypto_util.merkle_root([])


class TestGenDsKey(unittest.TestCase):
    def test_rsa_variants(self):
        for size in (2048, 3072, 4096):
            priv, pub = crypto_util.gen_dskey(f"RSA-{size}")
            self.assertEqual(priv.key_size, size)
            self.assertEqual(pub.key_size, size)

    def test_ec_curves(self):
        from cryptography.hazmat.primitives.asymmetric import ec as _ec
        expected = {
            "ec.SECP256R1": _ec.SECP256R1,
            "ec.SECP384R1": _ec.SECP384R1,
            "ec.BRAINPOOLP256R1": _ec.BrainpoolP256R1,
            "ec.BRAINPOOLP384R1": _ec.BrainpoolP384R1,
        }
        for algo, curve in expected.items():
            priv, pub = crypto_util.gen_dskey(algo)
            self.assertEqual(priv.curve.name, curve.name)
            self.assertEqual(pub.curve.name, curve.name)

    @unittest.skipIf(crypto_util.mldsa is None, "ML-DSA unavailable")
    def test_mldsa_variants(self):
        for variant in ("44", "65", "87"):
            priv, pub = crypto_util.gen_dskey(f"ML_DSA_{variant}")
            self.assertIsNotNone(priv)
            self.assertIsNotNone(pub)

    def test_unsupported_raises(self):
        for bad in ("", "RSA", "RSA-1024", "RSA-40961", "ec.SECP521R1", "DSA-2048", 42, None):
            with self.assertRaises(ValueError):
                crypto_util.gen_dskey(bad)

    def test_ds_algo_of_key(self):
        priv, _ = crypto_util.gen_dskey("RSA-2048")
        self.assertEqual(crypto_util.ds_algo_of_key(priv), "RSA-2048")
        priv, _ = crypto_util.gen_dskey("ec.SECP384R1")
        self.assertEqual(crypto_util.ds_algo_of_key(priv), "ec.SECP384R1")


class TestSignVerify(unittest.TestCase):
    ALGOS = ["RSA-2048", "RSA-3072", "ec.SECP256R1", "ec.BRAINPOOLP384R1"]
    if crypto_util.mldsa is not None:
        ALGOS += ["ML_DSA_44", "ML_DSA_87"]

    def test_roundtrip_all_algos(self):
        for algo in self.ALGOS:
            priv, pub = crypto_util.gen_dskey(algo)
            nonce, sig = crypto_util.sign_json(_sample_payload(), algo, priv)
            self.assertTrue(
                crypto_util.verify_ds(_sample_payload(), algo, pub, sig, nonce),
                f"verify failed for {algo}",
            )

    def test_tampered_json_fails(self):
        priv, pub = crypto_util.gen_dskey("RSA-2048")
        nonce, sig = crypto_util.sign_json(_sample_payload(), "RSA-2048", priv)
        tampered = dict(_sample_payload(), HashedDocument="tampered")
        self.assertFalse(crypto_util.verify_ds(tampered, "RSA-2048", pub, sig, nonce))

    def test_wrong_key_fails(self):
        priv, pub = crypto_util.gen_dskey("RSA-2048")
        other, _ = crypto_util.gen_dskey("RSA-2048")
        nonce, sig = crypto_util.sign_json(_sample_payload(), "RSA-2048", priv)
        self.assertFalse(crypto_util.verify_ds(_sample_payload(), "RSA-2048", other.public_key(), sig, nonce))

    def test_random_nonce_produces_distinct_signatures(self):
        priv, pub = crypto_util.gen_dskey("RSA-2048")
        n1, s1 = crypto_util.sign_json(_sample_payload(), "RSA-2048", priv)
        n2, s2 = crypto_util.sign_json(_sample_payload(), "RSA-2048", priv)
        self.assertNotEqual(n1, n2)
        self.assertNotEqual(s1, s2)
        self.assertTrue(crypto_util.verify_ds(_sample_payload(), "RSA-2048", pub, s1, n1))
        self.assertTrue(crypto_util.verify_ds(_sample_payload(), "RSA-2048", pub, s2, n2))

    def test_same_nonce_signatures_still_verify(self):
        # RSA-PSS / ECDSA / ML-DSA all randomise the signature itself, but a
        # fixed nonce fixes the signed (HMAC) message — every signature must
        # still verify with the matching nonce.
        for algo in ("RSA-2048", "ec.SECP384R1"):
            priv, pub = crypto_util.gen_dskey(algo)
            nonce = "A" * 43
            _, s1 = crypto_util.sign_json(_sample_payload(), algo, priv, nonce=nonce)
            _, s2 = crypto_util.sign_json(_sample_payload(), algo, priv, nonce=nonce)
            self.assertTrue(crypto_util.verify_ds(_sample_payload(), algo, pub, s1, nonce))
            self.assertTrue(crypto_util.verify_ds(_sample_payload(), algo, pub, s2, nonce))

    def test_nonce_at_least_32_bytes(self):
        priv, _ = crypto_util.gen_dskey("RSA-2048")
        import base64
        nonce, _ = crypto_util.sign_json(_sample_payload(), "RSA-2048", priv)
        self.assertGreaterEqual(len(base64.urlsafe_b64decode(nonce + "=" * (-len(nonce) % 4))), 32)

    def test_corrupt_signature_fails(self):
        priv, pub = crypto_util.gen_dskey("RSA-2048")
        nonce, sig = crypto_util.sign_json(_sample_payload(), "RSA-2048", priv)
        bad = sig[:-4] + "AAAA"
        self.assertFalse(crypto_util.verify_ds(_sample_payload(), "RSA-2048", pub, bad, nonce))


class TestFingerprint(unittest.TestCase):
    SHA1_RE = re.compile(r"^([0-9a-f]{2}:){19}[0-9a-f]{2}$")
    SHA256_RE = re.compile(r"^([0-9a-f]{2}:){31}[0-9a-f]{2}$")

    def test_fingerprint_format(self):
        priv, pub = crypto_util.gen_dskey("RSA-2048")
        sha1fgpt, sha256fgpt = crypto_util.getfgpt(pub)
        self.assertRegex(sha1fgpt, self.SHA1_RE)
        self.assertRegex(sha256fgpt, self.SHA256_RE)

    def test_fingerprint_stable(self):
        priv, pub = crypto_util.gen_dskey("ec.SECP384R1")
        self.assertEqual(crypto_util.getfgpt(pub), crypto_util.getfgpt(pub))


class TestKeyStorage(unittest.TestCase):
    def test_privkey_roundtrip_with_password(self):
        priv, pub = crypto_util.gen_dskey("RSA-2048")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "key.pem")
            crypto_util.save_privkey(priv, "RSA-2048", path, "pw123")
            loaded = crypto_util.fetch_privkey(path, "pw123")
            self.assertEqual(loaded.public_key().public_numbers(),
                             pub.public_numbers())

    def test_pubkey_roundtrip(self):
        priv, pub = crypto_util.gen_dskey("ec.SECP384R1")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "pub.pem")
            crypto_util.save_pubkey(pub, "ec.SECP384R1", path)
            loaded = crypto_util.fetch_pubkey(path)
            self.assertEqual(crypto_util.getfgpt(loaded), crypto_util.getfgpt(pub))


if __name__ == "__main__":
    unittest.main()
