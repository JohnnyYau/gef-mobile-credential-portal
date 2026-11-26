"""rag_indexer.py — build a searchable corpus from the chain + raw documents.

Corpus entries: one chain-info record, one per block (heights >= 1), and one
per raw credential JSON stored under ``<chain>/rawjsondocs/<hash>.json``.
Embeddings live in a FAISS IndexFlatIP (cosine over L2-normalised vectors).
The index rebuilds lazily whenever the chain changes (height or file mtimes).

Batch U5.1: the version stamp is a content digest rather than a max-mtime,
embeddings are cached on disk keyed by (stamp, backend, dim), the exact/vector
fusion is a standalone function, and an optional lexical reranker can reorder
vector candidates. Reranking is off by default — see ``RERANK_ENABLED``.
"""

import hashlib
import json
import os
import re
import threading

import numpy as np

from . import blockchain_util
from .config import CHAIN_DIR
from .rag_embedder import Embedder

HASH_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{40,}")
TOKEN_RE = re.compile(r"[a-z0-9]+")

# Lexical reranking is a reorder-only stage: it never adds or drops candidates.
# Enabled by default because it measurably improved recall@6 (0.8 -> 1.0) and
# MRR (0.567 -> 0.653) on the golden set while a wider candidate window alone
# changed nothing — see docs/U5.1_retrieval.md. Set RAG_RERANK=0 to disable.
RERANK_ENABLED = os.environ.get("RAG_RERANK", "1") != "0"
RERANK_WEIGHT = 0.25


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


def credential_entry(document, hashed_document):
    pp = document.get("PersonalParticulars", {})
    ai = document.get("AcademicInfo", {})
    di = document.get("DocumentInfo", {})
    # Display order follows the registry convention: Surname GivenNames.
    person_name = " ".join(x for x in (pp.get("Surname", ""), pp.get("GivenNames", "")) if x)
    parts = [
        f"Credential of {person_name}" if person_name else "Credential",
        f"student ID {pp.get('StudentID')}" if pp.get("StudentID") else "",
        f"sex {pp.get('Sex')}" if pp.get("Sex") else "",
        f"degree {ai.get('DegreeName')}" if ai.get("DegreeName") else "",
        ("courses: "
         + ", ".join(str(c.get("CourseDescr", "")) for c in ai.get("Courses", [])))
        if ai.get("Courses") else "",
        f"GPA {ai.get('GPA')}" if ai.get("GPA") else "",
        (f"issued {di.get('DateOfIssue')} by {di.get('IssuingO')}"
         + (f" ({di.get('IssuingOU')})" if di.get("IssuingOU") else ""))
        if di.get("IssuingO") else "",
        f"document type {di.get('DocType')}" if di.get("DocType") else "",
        f"document hash {hashed_document}",
    ]
    return {
        "id": f"credential:{hashed_document}",
        "kind": "credential",
        "hashed_document": hashed_document,
        "student_id": str(pp.get("StudentID") or ""),
        "person_name": person_name,
        "surname": str(pp.get("Surname") or ""),
        "given_names": str(pp.get("GivenNames") or ""),
        "text": ". ".join(p for p in parts if p) + ".",
        "meta": {"document": document},
    }


def build_corpus(chain):
    """List of corpus entries (dicts with id/kind/text/meta)."""
    info = blockchain_util.read_info(chain)
    height = blockchain_util.last_height(chain)

    signers = ", ".join(
        f"{s.get('name')} ({s.get('ds_algo')})" for s in info.get("trusted_signers", [])
    ) or "none"
    entries = [{
        "id": "chain:info",
        "kind": "chain",
        "text": (f"Chain {info.get('chain_name')} uses content hash algorithm "
                 f"{info.get('content_hash_algo')}, current height {height}. "
                 f"Trusted data signers: {signers}."),
        "meta": {},
    }]

    for h in range(1, height + 1):
        try:
            block = blockchain_util.load_block(chain, h)
        except (OSError, ValueError):
            continue
        payload = block.get("payload", {})
        action = payload.get("action", "?")
        lines = [
            f"Block height {h}, action {action}, "
            f"content hash algorithm {block.get('contentHashAlgo')}."
        ]
        if action == "ISSUE":
            di = payload.get("DocumentInfo", {})
            lines.append(
                f"Document hash {payload.get('HashedDocument')}. "
                f"Issuing organization {di.get('IssuingO')}, "
                f"unit {di.get('IssuingOU')}, document type {di.get('DocType')}, "
                f"date of issue {di.get('DateOfIssue')}."
            )
            fgpts = [d.get("DSsha256fgpt", "")[:12] + "..." for d in
                     block.get("DataSignatureInfo", [])]
            lines.append(f"Signed by {len(fgpts)} data signer(s): {', '.join(fgpts)}.")
        elif action == "REVOKE":
            lines.append(f"Revokes document hash {payload.get('HashedDocument')}.")
        entries.append({
            "id": f"block-{h:09d}",
            "kind": "block",
            "action": action,
            "height": h,
            "hashed_document": payload.get("HashedDocument", ""),
            "text": " ".join(lines),
            "meta": {"block": block},
        })

    raw_dir = os.path.join(chain, "rawjsondocs")
    if os.path.isdir(raw_dir):
        for filename in sorted(os.listdir(raw_dir)):
            if not filename.endswith(".json"):
                continue
            hashed_document = filename[:-5]
            try:
                with open(os.path.join(raw_dir, filename), encoding="utf-8") as fh:
                    document = json.load(fh)
            except (OSError, ValueError):
                continue
            entries.append(credential_entry(document, hashed_document))

    return entries


def _stamp_digest(chain) -> tuple:
    """(height, digest) describing the chain's retrieval-relevant content.

    A content digest beats a max-mtime: two writes inside the same mtime tick
    (common on FAT/NTFS at second granularity) would otherwise look unchanged
    and the index would keep serving the old corpus.
    """
    h = hashlib.sha256()
    info_path = os.path.join(chain, "info.yaml")
    if os.path.exists(info_path):
        h.update(f"info:{os.path.getmtime(info_path):.6f}".encode())
    for directory in ("blocks", "rawjsondocs"):
        path = os.path.join(chain, directory)
        if not os.path.isdir(path):
            continue
        h.update(directory.encode())
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            h.update(f"{name}:{st.st_mtime_ns}:{st.st_size}".encode())
    return blockchain_util.last_height(chain), h.hexdigest()[:32]


def cache_path(chain, backend: str, dim: int) -> str:
    """Embedding cache beside the chain dir, not inside it.

    Keeping it out of the chain directory matters: anything dropped into
    ``blocks/`` or ``rawjsondocs/`` would change the corpus and the stamp.
    """
    parent = os.path.dirname(os.path.abspath(chain))
    name = os.path.basename(os.path.abspath(chain))
    safe_backend = re.sub(r"[^A-Za-z0-9_.-]", "_", backend)
    return os.path.join(parent, "rag-cache", f"{name}-{safe_backend}-{dim}.npz")


def load_cached_vectors(path: str, stamp: tuple, entry_ids: list) -> np.ndarray | None:
    """Vectors from a matching cache file, or None (never raise)."""
    try:
        with np.load(path, allow_pickle=False) as data:
            vectors = data["vectors"]
            meta = json.loads(str(data["meta"][0]))
    except (OSError, ValueError, KeyError, IndexError):
        return None
    if meta.get("stamp") != list(stamp) or meta.get("entry_ids") != entry_ids:
        return None
    if vectors.shape[0] != len(entry_ids):
        return None
    return vectors


def save_vectors(path: str, vectors: np.ndarray, stamp: tuple,
                 entry_ids: list, backend: str, dim: int) -> bool:
    """Write the cache atomically; a failure only costs a rebuild later.

    The temp name must end in ``.npz`` because ``np.savez`` appends that
    suffix to anything else — writing ``x.npz.tmp`` silently produces
    ``x.npz.tmp.npz`` and the rename then fails, so the cache would never be
    written at all.
    """
    meta = json.dumps({"stamp": list(stamp), "entry_ids": entry_ids,
                       "backend": backend, "dim": dim})
    tmp = path[:-4] + ".tmp.npz" if path.endswith(".npz") else path + ".tmp.npz"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez(tmp, vectors=vectors, meta=np.array([meta]))
        os.replace(tmp, path)
        return True
    except (OSError, ValueError):
        return False


# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------


class RagIndex:
    def __init__(self):
        self._lock = threading.Lock()
        self._stamp = None
        self._entries = []
        self._by_hash = {}
        self._index = None
        self._embedder = None

    # -- lifecycle ---------------------------------------------------------

    def _current_stamp(self):
        return _stamp_digest(str(CHAIN_DIR))

    def ensure_ready(self):
        with self._lock:
            stamp = self._current_stamp()
            if stamp == self._stamp and self._index is not None:
                return
            self._rebuild(stamp)

    def _rebuild(self, stamp=None):
        chain = str(CHAIN_DIR)
        entries = build_corpus(chain)
        if not entries:
            entries = [{
                "id": "chain:info", "kind": "chain",
                "text": "The chain is empty.",
                "meta": {},
            }]
        texts = [e["text"] for e in entries]
        entry_ids = [e["id"] for e in entries]
        embedder = Embedder()
        stamp = stamp or self._current_stamp()

        cache = cache_path(chain, embedder.backend, embedder.dim)
        vectors = load_cached_vectors(cache, stamp, entry_ids)
        self._cache_state = "hit" if vectors is not None else "built"
        if vectors is None:
            vectors = embedder.encode(texts)
            if save_vectors(cache, vectors, stamp, entry_ids,
                            embedder.backend, embedder.dim):
                self._cache_state = "built+saved"

        self._entries = entries
        self._vectors = vectors
        self._embedder = embedder
        self._index = self._build_vector_index(vectors, embedder.dim)
        self._by_hash = {
            e["hashed_document"]: e
            for e in entries if e.get("hashed_document")
        }
        self._stamp = stamp

    @staticmethod
    def _build_vector_index(vectors, dim):
        """FAISS IndexFlatIP when available; a numpy brute-force cosine
        search otherwise — same interface, same retrieval results."""
        try:
            import faiss  # local import: optional dependency
            index = faiss.IndexFlatIP(dim)
            index.add(vectors)
            return index
        except ImportError:
            return None

    # -- search ------------------------------------------------------------

    def search(self, query, k=6):
        self.ensure_ready()

        # 1. exact hash hit (highest confidence, no embedding needed)
        exact = []
        for token in HASH_TOKEN_RE.findall(query or ""):
            entry = self._by_hash.get(token)
            if entry is not None:
                exact.append(self._view(entry, 1.0))
                break

        # 2. vector search (candidates, not yet fused)
        vector = self._embedder.encode([query])[0]
        hits = self._vector_search(vector, max(k, k * 2 if RERANK_ENABLED else k))
        candidates = [(float(score), self._entries[int(idx)])
                      for score, idx in hits]
        if RERANK_ENABLED:
            candidates = rerank(query, candidates, RERANK_WEIGHT)
        vector_views = [self._view(entry, score) for score, entry in candidates]

        return fuse_exact_and_vector(exact, vector_views, k)

    def _vector_search(self, vector, k):
        if self._index is not None:
            scores, indexes = self._index.search(
                np.ascontiguousarray(vector.reshape(1, -1)), k
            )
            return list(zip(scores[0], indexes[0]))
        # numpy fallback: cosine over L2-normalised rows
        dots = np.dot(self._vectors, vector)
        order = np.argsort(dots)[::-1][:k]
        return [(dots[i], i) for i in order]

    def stats(self):
        self.ensure_ready()
        return {
            "entries": len(self._entries),
            "embedder": self._embedder.backend,
            "dim": self._embedder.dim,
            "cache": getattr(self, "_cache_state", "unknown"),
            "rerank": RERANK_ENABLED,
            "stamp": list(self._stamp) if self._stamp else None,
        }

    @staticmethod
    def _view(entry, score):
        view = {
            "id": entry["id"],
            "kind": entry.get("kind"),
            "text": entry["text"],
            "score": round(score, 4),
        }
        for key in ("height", "action", "hashed_document",
                    "student_id", "person_name", "surname", "given_names"):
            if entry.get(key):
                view[key] = entry[key]
        return view


def fuse_exact_and_vector(exact, vector_views, k):
    """Merge the exact-hit list with vector candidates (batch U5.1).

    The exact hit always stays first: a hash the query literally contains is a
    stronger signal than any similarity score. Duplicates are dropped by id so
    the same credential cannot occupy two slots.
    """
    merged = list(exact)
    seen = {m["id"] for m in merged}
    for view in vector_views:
        if view["id"] in seen:
            continue
        merged.append(view)
        seen.add(view["id"])
    return merged[:k]


def lexical_overlap(query: str, text: str) -> float:
    """Fraction of query tokens present in the text (0..1)."""
    q = {t for t in TOKEN_RE.findall((query or "").lower()) if len(t) > 1}
    if not q:
        return 0.0
    d = {t for t in TOKEN_RE.findall((text or "").lower()) if len(t) > 1}
    return len(q & d) / len(q)


def rerank(query, candidates, weight=RERANK_WEIGHT):
    """Reorder candidates by score + lexical overlap. Never adds or drops.

    ``candidates`` is a list of (score, entry). Reordering only means the fused
    list can improve without changing recall of the candidate set.
    """
    reranked = []
    for score, entry in candidates:
        bonus = lexical_overlap(query, entry.get("text", ""))
        reranked.append((score + weight * bonus, entry))
    reranked.sort(key=lambda item: item[0], reverse=True)
    return reranked


_index_singleton = None
_index_lock = threading.Lock()


def get_index():
    """Process-wide RagIndex singleton (lazily built on first search)."""
    global _index_singleton
    with _index_lock:
        if _index_singleton is None:
            _index_singleton = RagIndex()
        return _index_singleton
