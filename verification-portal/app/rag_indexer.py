"""rag_indexer.py — build a searchable corpus from the chain + raw documents.

Corpus entries: one chain-info record, one per block (heights >= 1), and one
per raw credential JSON stored under ``<chain>/rawjsondocs/<hash>.json``.
Embeddings live in a FAISS IndexFlatIP (cosine over L2-normalised vectors).
The index rebuilds lazily whenever the chain changes (height or file mtimes).
"""

import json
import os
import re
import threading

import numpy as np

from . import blockchain_util
from .config import CHAIN_DIR
from .rag_embedder import Embedder

HASH_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{40,}")


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
        f"date of birth {pp.get('DOB')}" if pp.get("DOB") else "",
        f"sex {pp.get('Sex')}" if pp.get("Sex") else "",
        f"degree {ai.get('DegreeName')}" if ai.get("DegreeName") else "",
        (f"courses: "
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
        chain = str(CHAIN_DIR)
        stamps = []
        info_path = os.path.join(chain, "info.yaml")
        if os.path.exists(info_path):
            stamps.append(os.path.getmtime(info_path))
        for directory in ("blocks", "rawjsondocs"):
            path = os.path.join(chain, directory)
            if os.path.isdir(path):
                stamps.extend(
                    os.path.getmtime(os.path.join(path, name)) for name in os.listdir(path)
                )
        return (blockchain_util.last_height(str(CHAIN_DIR)), max(stamps) if stamps else 0)

    def ensure_ready(self):
        with self._lock:
            stamp = self._current_stamp()
            if stamp == self._stamp and self._index is not None:
                return
            self._rebuild()

    def _rebuild(self):
        chain = str(CHAIN_DIR)
        entries = build_corpus(chain)
        embedder = Embedder()
        if not entries:
            entries = [{
                "id": "chain:info", "kind": "chain",
                "text": "The chain is empty.",
                "meta": {},
            }]
        texts = [e["text"] for e in entries]
        vectors = embedder.encode(texts)

        self._entries = entries
        self._vectors = vectors
        self._embedder = embedder
        self._index = self._build_vector_index(vectors, embedder.dim)
        self._by_hash = {
            e["hashed_document"]: e
            for e in entries if e.get("hashed_document")
        }
        self._stamp = self._current_stamp()

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
        results = []

        # 1. exact hash hit (highest confidence, no embedding needed)
        for token in HASH_TOKEN_RE.findall(query or ""):
            entry = self._by_hash.get(token)
            if entry is not None:
                results.append(self._view(entry, 1.0))
                break

        # 2. vector search
        vector = self._embedder.encode([query])[0]
        scores = self._vector_search(vector, k)
        for score, idx in scores:
            entry = self._entries[int(idx)]
            view = self._view(entry, float(score))
            if not any(v["id"] == view["id"] for v in results):
                results.append(view)

        return results[:k]

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


_index_singleton = None
_index_lock = threading.Lock()


def get_index():
    """Process-wide RagIndex singleton (lazily built on first search)."""
    global _index_singleton
    with _index_lock:
        if _index_singleton is None:
            _index_singleton = RagIndex()
        return _index_singleton
