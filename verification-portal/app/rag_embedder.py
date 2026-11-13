"""rag_embedder.py — text embeddings for the RAG chat.

Primary backend: sentence-transformers all-MiniLM-L6-v2 (CPU, ~90 MB model).
If the model or torch cannot be loaded (no network, no disk, import error),
a deterministic hashing embedder keeps retrieval working with zero external
dependencies — same interface, same FAISS index.
"""

import hashlib
import logging
import os
import re

logger = logging.getLogger("rag")

EMBED_MODEL = os.environ.get("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
TOKEN_RE = re.compile(r"[a-z0-9]+")
FALLBACK_DIM = 1024


def _try_load_sentence_transformer():
    """Return a SentenceTransformer or None (never raise)."""
    try:
        from sentence_transformers import SentenceTransformer  # local import: heavy
        model = SentenceTransformer(EMBED_MODEL)
        logger.info("Embedder: sentence-transformers %s", EMBED_MODEL)
        return model
    except Exception as exc:  # pragma: no cover — environment dependent
        logger.warning("sentence-transformers unavailable (%s); using hashing embedder", exc)
        return None


class Embedder:
    """Normalised float32 vectors; both backends return L2-normalised rows."""

    def __init__(self):
        self._st = _try_load_sentence_transformer()
        if self._st is not None:
            self.dim = self._st.get_sentence_embedding_dimension()
            self.backend = "sentence-transformers/" + EMBED_MODEL.split("/")[-1]
        else:
            self.dim = FALLBACK_DIM
            self.backend = "hash-ngrams-v1"

    def encode(self, texts):
        if self._st is not None:
            vecs = self._st.encode(
                list(texts), normalize_embeddings=True, show_progress_bar=False
            )
            return vecs.astype("float32")
        return self._hash_encode(texts)

    @staticmethod
    def _hash_encode(texts):
        """TF-hashing over alphanumeric tokens, L2-normalised, dim 1024."""
        import numpy as np
        out = np.zeros((len(texts), FALLBACK_DIM), dtype="float32")
        for i, text in enumerate(texts):
            counts = {}
            for token in TOKEN_RE.findall(text.lower()):
                counts[token] = counts.get(token, 0) + 1
            for token, count in counts.items():
                idx = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % FALLBACK_DIM
                out[i, idx] += count
            norm = float(np.linalg.norm(out[i]))
            if norm > 0:
                out[i] /= norm
        return out
