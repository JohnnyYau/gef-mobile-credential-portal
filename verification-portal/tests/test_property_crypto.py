"""U4.2 property + crypto tests (hypothesis, MPL-2.0 — permissive, not copyleft).

Four properties over the hashing/signature core:

1. canonicalisation is order-independent;
2. merkle root follows the documented duplicate-last rule and is order
   sensitive;
3. any field mutation changes the digest (tamper always breaks the hash);
4. ``verify_ds`` answers False on malformed input instead of raising.

Plus an algorithm dispatch matrix (ML-DSA / RSA-PSS / ECDSA, positive and
negative). Keys are generated once per class: generating an ML-DSA key is
measurably slower than a hash call, and the property tests do not need a new
one each example.
"""

from __future__ import annotations

import base64
import json
import random
import unittest

from app import crypto_util
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests._bootstrap import isolated_chain_dir  # noqa: F401  (ensures env order)

# Cheap, deterministic property runs: the assertions are exact (no floats, no
# network), so a small example count still exercises the real code paths.
PROPS = settings(max_examples=60, deadline=None,
                 suppress_health_check=[HealthCheck.too_slow])


# --------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------

scalars = st.one_of(st.none(), st.booleans(),
                    st.integers(-10 ** 6, 10 ** 6),
                    st.text(max_size=12),
                    st.floats(allow_nan=False, allow_infinity=False,
                              width=32))

json_values = st.recursive(
    scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.text(min_size=1, max_size=6), children,
                        max_size=3)),
    max_leaves=8)


def _reorder(value, rng):
    """Rebuild the same logical value with dict keys inserted in random order."""
    if isinstance(value, dict):
        items = list(value.items())
        rng.shuffle(items)
        return {k: _reorder(v, rng) for k, v in items}
    if isinstance(value, list):
        return [_reorder(v, rng) for v in value]
    return value


def _with_one_field_changed(value, rng):
    """Return a copy with exactly one scalar replaced by a different scalar."""
    replacements = [None, True, False, 0, 1, -1, "x", "y", "", 3.5]

    def walk(node, path):
        if isinstance(node, dict) and node:
            k = rng.choice(list(node.keys()))
            return {**node, k: _mutate(node[k], path + [str(k)])}
        if isinstance(node, list) and node:
            i = rng.randrange(len(node))
            return [*node[:i], _mutate(node[i], path + [i]), *node[i + 1:]]
        return node

    def _mutate(node, path):
        if isinstance(node, (dict, list)) and node:
            return walk(node, path)
        current = node
        for cand in replacements:
            if type(cand) is type(current) and cand != current:
                return cand
        return "changed" if current != "changed" else 1

    return walk(value, [])


# --------------------------------------------------------------------------
# 1. Canonicalisation determinism
# --------------------------------------------------------------------------


class CanonicalisationTests(unittest.TestCase):
    @PROPS
    @given(payload=json_values, seed=st.integers(0, 2 ** 31))
    def test_key_order_does_not_change_the_hash(self, payload, seed):
        rng = random.Random(seed)
        reordered = _reorder(payload, rng)
        self.assertEqual(crypto_util.hash_json(payload),
                         crypto_util.hash_json(reordered))

    @PROPS
    @given(payload=json_values)
    def test_hash_is_stable_across_repeat_calls(self, payload):
        self.assertEqual(crypto_util.hash_json(payload),
                         crypto_util.hash_json(json.loads(json.dumps(payload))))

    @PROPS
    @given(payload=json_values)
    def test_digest_is_base64url_without_padding(self, payload):
        digest = crypto_util.hash_json(payload)
        self.assertNotIn("=", digest)
        self.assertNotIn("+", digest)
        self.assertNotIn("/", digest)

    def test_unsupported_algorithm_raises(self):
        with self.assertRaises(ValueError):
            crypto_util.hash_json({"a": 1}, "not-a-real-hash")


# --------------------------------------------------------------------------
# 2. Merkle root
# --------------------------------------------------------------------------


class MerkleTests(unittest.TestCase):
    def test_single_leaf_is_its_own_root(self):
        leaf = crypto_util.hash_bytes(b"only")
        self.assertEqual(crypto_util.merkle_root([leaf]), leaf)

    @PROPS
    @given(seeds=st.lists(st.text(min_size=1, max_size=8), min_size=2, max_size=7))
    def test_odd_level_duplicates_the_last_leaf(self, seeds):
        leaves = [crypto_util.hash_bytes(s.encode("utf-8")) for s in seeds]
        expected = leaves[:]
        while len(expected) > 1:
            nxt = []
            for i in range(0, len(expected), 2):
                left = expected[i]
                right = expected[i + 1] if i + 1 < len(expected) else left
                nxt.append(crypto_util.hash_bytes((left + right).encode("ascii")))
            expected = nxt
        self.assertEqual(crypto_util.merkle_root(leaves), expected[0])

    @PROPS
    @given(a=st.text(min_size=1, max_size=6), b=st.text(min_size=1, max_size=6))
    def test_order_matters_for_distinct_leaves(self, a, b):
        if a == b:
            return
        la = crypto_util.hash_bytes(a.encode("utf-8"))
        lb = crypto_util.hash_bytes(b.encode("utf-8"))
        self.assertNotEqual(crypto_util.merkle_root([la, lb]),
                            crypto_util.merkle_root([lb, la]))

    def test_empty_leaf_list_is_rejected(self):
        with self.assertRaises(ValueError):
            crypto_util.merkle_root([])


# --------------------------------------------------------------------------
# 3. Tampering always changes the digest
# --------------------------------------------------------------------------


class TamperTests(unittest.TestCase):
    @PROPS
    @given(payload=json_values, seed=st.integers(0, 2 ** 31))
    def test_any_single_field_change_changes_the_hash(self, payload, seed):
        if not isinstance(payload, (dict, list)) or not payload:
            return  # nothing to mutate
        rng = random.Random(seed)
        changed = _with_one_field_changed(payload, rng)
        if changed == payload:
            return
        self.assertNotEqual(crypto_util.hash_json(payload),
                            crypto_util.hash_json(changed))

    def test_extra_key_changes_the_hash(self):
        base = {"A": 1, "B": 2}
        self.assertNotEqual(crypto_util.hash_json(base),
                            crypto_util.hash_json({**base, "C": None}))

    def test_dropping_a_key_changes_the_hash(self):
        base = {"A": 1, "B": 2}
        self.assertNotEqual(crypto_util.hash_json(base),
                            crypto_util.hash_json({"A": 1}))

    def test_type_swap_changes_the_hash(self):
        # 1 and "1" canonicalise differently; a lenient hash would collide.
        self.assertNotEqual(crypto_util.hash_json({"A": 1}),
                            crypto_util.hash_json({"A": "1"}))


# --------------------------------------------------------------------------
# 4. verify_ds never raises
# --------------------------------------------------------------------------


class VerifyRobustnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.priv, cls.pub = crypto_util.gen_dskey("ec.SECP256R1")
        cls.payload = {"DocumentInfo": {"DocType": "diploma"}}
        cls.nonce, cls.sig = crypto_util.sign_json(
            cls.payload, "ec.SECP256R1", cls.priv)

    @PROPS
    @given(sig=st.text(max_size=200), nonce=st.text(max_size=64),
           payload=json_values)
    def test_random_garbage_returns_false_not_exception(self, sig, nonce, payload):
        self.assertFalse(crypto_util.verify_ds(payload, "ec.SECP256R1",
                                              self.pub, sig, nonce))

    def test_empty_signature_is_false(self):
        self.assertFalse(crypto_util.verify_ds(self.payload, "ec.SECP256R1",
                                              self.pub, "", self.nonce))

    def test_bad_nonce_is_false(self):
        self.assertFalse(crypto_util.verify_ds(self.payload, "ec.SECP256R1",
                                              self.pub, self.sig, "wrong-nonce"))

    def test_non_base64_signature_is_false(self):
        self.assertFalse(crypto_util.verify_ds(self.payload, "ec.SECP256R1",
                                              self.pub, "!!!not base64!!!",
                                              self.nonce))

    def test_unknown_key_object_is_false(self):
        self.assertFalse(crypto_util.verify_ds(self.payload, "ec.SECP256R1",
                                              object(), self.sig, self.nonce))

    def test_unsupported_hash_algo_is_false(self):
        self.assertFalse(crypto_util.verify_ds(self.payload, "ec.SECP256R1",
                                              self.pub, self.sig, self.nonce,
                                              "not-a-real-hash"))

    def test_truncated_signature_is_false(self):
        cut = self.sig[: len(self.sig) // 2]
        self.assertFalse(crypto_util.verify_ds(self.payload, "ec.SECP256R1",
                                              self.pub, cut, self.nonce))

    def test_signature_valid_only_for_the_signed_payload(self):
        self.assertTrue(crypto_util.verify_ds(self.payload, "ec.SECP256R1",
                                              self.pub, self.sig, self.nonce))
        self.assertFalse(crypto_util.verify_ds(
            {"DocumentInfo": {"DocType": "degree"}}, "ec.SECP256R1",
            self.pub, self.sig, self.nonce))


# --------------------------------------------------------------------------
# 5. Algorithm dispatch matrix
# --------------------------------------------------------------------------


class AlgorithmMatrixTests(unittest.TestCase):
    PAYLOAD = {"HolderInfo": {"Surname": "Chan"}, "DegreeInfo": {"Degree": "BSc"}}

    @classmethod
    def setUpClass(cls):
        cls.keys = {}
        for algo in ("ML_DSA_65", "RSA-2048", "ec.SECP256R1"):
            cls.keys[algo] = crypto_util.gen_dskey(algo)

    def test_positive_and_negative_for_every_algorithm(self):
        for algo, (priv, pub) in self.keys.items():
            with self.subTest(algo=algo):
                nonce, sig = crypto_util.sign_json(self.PAYLOAD, algo, priv)
                self.assertTrue(crypto_util.verify_ds(self.PAYLOAD, algo,
                                                     pub, sig, nonce))
                # same signature, different message
                self.assertFalse(crypto_util.verify_ds(
                    {**self.PAYLOAD, "DegreeInfo": {"Degree": "MSc"}},
                    algo, pub, sig, nonce))
                # same message, different nonce
                self.assertFalse(crypto_util.verify_ds(self.PAYLOAD, algo, pub,
                                                       sig, nonce + "x"))
                # same message, other key
                other_priv, other_pub = crypto_util.gen_dskey(algo)
                self.assertFalse(crypto_util.verify_ds(self.PAYLOAD, algo,
                                                       other_pub, sig, nonce))
                self.assertTrue(other_priv is not None)

    def test_fixed_nonce_makes_both_signatures_valid_but_not_identical(self):
        """A fixed nonce fixes the *message*, not the signature bytes.

        RSA-PSS salts randomly and ECDSA draws a fresh k, so re-signing the
        same payload with the same nonce yields a different (equally valid)
        signature. That is why anything that dedupes issued credentials must
        key on the payload hash, never on the signature.
        """
        fixed = "fixed-nonce-for-test"
        for algo, (priv, pub) in self.keys.items():
            with self.subTest(algo=algo):
                n1, s1 = crypto_util.sign_json(self.PAYLOAD, algo, priv,
                                              nonce=fixed)
                n2, s2 = crypto_util.sign_json(self.PAYLOAD, algo, priv,
                                              nonce=fixed)
                self.assertEqual((n1, n2), (fixed, fixed))
                self.assertTrue(crypto_util.verify_ds(self.PAYLOAD, algo,
                                                     pub, s1, n1))
                self.assertTrue(crypto_util.verify_ds(self.PAYLOAD, algo,
                                                     pub, s2, n2))
                if algo in ("RSA-2048", "ec.SECP256R1"):
                    self.assertNotEqual(s1, s2)


class SignatureEncodingTests(unittest.TestCase):
    def test_signature_is_urlsafe_b64(self):
        priv, _ = crypto_util.gen_dskey("ec.SECP256R1")
        _, sig = crypto_util.sign_json({"a": 1}, "ec.SECP256R1", priv)
        self.assertNotIn("=", sig)
        base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))


if __name__ == "__main__":
    unittest.main()
