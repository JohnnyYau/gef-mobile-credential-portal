"""Batch U8.3 — optional dependencies must degrade, not explode.

The portal installs with a lean image: `sentence-transformers`, `faiss-cpu`,
`scikit-learn` and `qrcode` are optional. Each is imported *locally*, at the
point of use, with an explicit fallback. That property is easy to break by
accident (a top-level import added for convenience), and it only breaks on the
machine that lacks the package — i.e. on the deployed image, never on the dev
box. These tests block the import and assert the documented fallback:

* no sentence-transformers -> hashing embedder (same interface, dim 1024)
* no faiss                -> numpy brute-force cosine over the same vectors
* no scikit-learn         -> rule-based anomaly flags only
* no qrcode               -> 503 with a message naming the missing package
"""

import builtins
import unittest
from contextlib import contextmanager

import numpy as np

from tests._bootstrap import isolated_chain_dir


@contextmanager
def import_blocked(*names):
    """Make ``import <name>`` raise ImportError, wherever it happens."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        root = name.split(".")[0]
        if root in names:
            raise ImportError(f"blocked by test: {name}")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = fake_import
    try:
        yield
    finally:
        builtins.__import__ = real_import


def setUpModule():
    isolated_chain_dir(prefix="gef26-u83-")
    import app.anomaly as anomaly_mod
    import app.chain_service as chain_mod
    import app.rag_embedder as embedder_mod
    import app.rag_indexer as indexer_mod
    global anomaly, chain_service, rag_embedder, rag_indexer
    anomaly, chain_service = anomaly_mod, chain_mod
    rag_embedder, rag_indexer = embedder_mod, indexer_mod
    chain_mod.ensure_chain()


class EmbedderFallbackTests(unittest.TestCase):
    def test_hashes_when_sentence_transformers_is_absent(self):
        with import_blocked("sentence_transformers"):
            embedder = rag_embedder.Embedder()
        self.assertEqual(embedder.backend, "hash-ngrams-v1")
        self.assertEqual(embedder.dim, rag_embedder.FALLBACK_DIM)
        vectors = embedder.encode(["diploma in computer science", "transcript"])
        self.assertEqual(vectors.shape, (2, rag_embedder.FALLBACK_DIM))
        # L2-normalised rows: retrieval scores must be comparable across backends
        norms = np.linalg.norm(vectors, axis=1)
        self.assertTrue(np.allclose(norms, 1.0, atol=1e-5), norms)


class VectorSearchFallbackTests(unittest.TestCase):
    def test_builds_no_faiss_index_when_faiss_is_absent(self):
        with import_blocked("faiss"):
            index = rag_indexer.RagIndex._build_vector_index(
                np.eye(4, dtype="float32"), 4)
        self.assertIsNone(index)

    def test_numpy_search_ranks_by_cosine(self):
        index = object.__new__(rag_indexer.RagIndex)   # no __init__, no cache
        index._index = None
        index._vectors = np.array([[1.0, 0.0], [0.0, 1.0], [0.8, 0.6]],
                                  dtype="float32")
        hits = index._vector_search(np.array([1.0, 0.0], dtype="float32"), 2)
        self.assertEqual(hits[0][1], 0)                # exact axis match first
        self.assertEqual(len(hits), 2)
        self.assertAlmostEqual(float(hits[0][0]), 1.0, places=5)


class AnomalyFallbackTests(unittest.TestCase):
    def test_rule_flags_still_returned_without_sklearn(self):
        counts = {("signer-a", 5): 9, ("signer-a", 6): 1}
        last_height = {("signer-a", 5): 7, ("signer-a", 6): 8}
        with import_blocked("sklearn"):
            forest = anomaly._isolation_flags(counts, last_height)
            report = anomaly.detect(str(chain_service.CHAIN_DIR))
        self.assertIsNone(forest)
        self.assertIn("anomalies", report)
        self.assertIsInstance(report["anomalies"], list)
        self.assertEqual(report["method"], "rule_based",
                         "without sklearn the report must not claim a model")


class QrFallbackTests(unittest.TestCase):
    def test_qr_endpoint_reports_the_missing_package(self):
        import app.main as main_mod
        from fastapi.testclient import TestClient
        with TestClient(main_mod.app) as client:
            demo = client.get("/api/demo/credentials").json()
            hashed = demo["diploma"]["hashed_document"]
            with import_blocked("qrcode"):
                res = client.get(f"/api/qr/{hashed}")
        self.assertEqual(res.status_code, 503)
        self.assertIn("qrcode", res.json()["detail"])


if __name__ == "__main__":
    unittest.main()
