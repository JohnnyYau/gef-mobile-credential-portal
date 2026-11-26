"""RAG chat tests (Week 2): retrieval + chat endpoint + offline generator.

Uses an isolated chain; no API keys set, so the offline generator answers.
If sentence-transformers cannot load (no network for the model download) the
embedder falls back to hashing — retrieval tests still hold because query and
corpus share name/ID tokens.
"""

import json
import shutil
import unittest
from unittest import mock

from tests._bootstrap import isolated_chain_dir

# Isolated chain + force the offline generator (must precede app import).
_TMP = isolated_chain_dir(
    prefix="portal-rag-test-",
    DEEPSEEK_API_KEY=None,
    OLLAMA_BASE_URL=None,
)

from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class RagTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)

    def test_rag_status(self):
        res = self.client.get("/api/rag/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("offline", data["generator"])
        self.assertGreaterEqual(data["index_entries"], 1)

    def test_chat_suggestions(self):
        res = self.client.get("/api/chat/suggestions")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["suggestions"])

    def test_chat_empty_question_422(self):
        res = self.client.post("/api/chat", json={"question": "   "})
        self.assertEqual(res.status_code, 422)

    def test_chat_name_question_valid(self):
        res = self.client.post("/api/chat", json={
            "question": "Has CHAN TAI MAN's diploma been revoked?"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("CHAN TAI MAN", data["answer"])
        self.assertIn("VALID", data["answer"].upper())
        self.assertEqual(data["generator"], "offline")
        self.assertTrue(data["sources"])
        self.assertGreaterEqual(data["retrieval"]["hits"], 1)

    def test_chat_hash_question(self):
        h = self.client.get("/api/demo/credentials").json()["diploma"]["hashed_document"]
        data = self.client.post("/api/chat", json={
            "question": f"Status of {h}"
        }).json()
        self.assertIn("VALID", data["answer"].upper())
        self.assertTrue(data["sources"])

    def test_chat_revoke_lifecycle(self):
        new_doc = json.loads(json.dumps(SAMPLE_DIPLOMA))
        new_doc["PersonalParticulars"]["StudentID"] = "77778888"
        issued = self.client.post("/api/issue", json={"document": new_doc}).json()
        h = issued["hashed_document"]
        self.client.post("/api/revoke", json={"hashed_document": h})

        data = self.client.post("/api/chat", json={
            "question": f"Is the credential with hash {h} revoked?"
        }).json()
        self.assertIn("REVOKED", data["answer"].upper())
        self.assertTrue(data["sources"])

    def test_chat_revoked_by_student_id(self):
        data = self.client.post("/api/chat", json={
            "question": "Is the credential of student 77778888 still valid?"
        }).json()
        self.assertIn("REVOKED", data["answer"].upper())

    def test_retrieval_transcript_hit(self):
        data = self.client.post("/api/chat", json={
            "question": "Transcript with course MATH1101 Elementary arithmetic"
        }).json()
        ids = [s["id"] for s in data["sources"]]
        self.assertTrue(any("credential" in i for i in ids), ids)

    def test_chat_count_question(self):
        data = self.client.post("/api/chat", json={
            "question": "How many blocks are on the chain?"
        }).json()
        self.assertIn("blocks in total", data["answer"])
        self.assertIn("ISSUE", data["answer"])

    def test_chat_signer_question(self):
        data = self.client.post("/api/chat", json={
            "question": "Who is the trusted signer of this chain?"
        }).json()
        self.assertIn("UNIVERSITY OF UTOPIA", data["answer"])

    def test_chat_exposes_generation_contract(self):
        data = self.client.post("/api/chat", json={
            "question": "How many blocks are on the chain?"
        }).json()
        gen = data["generation"]
        self.assertEqual(gen["degraded"], [])
        self.assertTrue(gen["validation_ok"])
        self.assertFalse(gen["sources_are_fallback"])


class RetrievalEngineeringTests(unittest.TestCase):
    """U5.1: version stamp, embedding cache, fusion and rerank contract."""

    def setUp(self):
        from app import chain_service, rag_indexer
        # The previous class removes its temp chain in tearDownClass; re-seed so
        # these retrieval tests always start from a real chain.
        chain_service.ensure_chain()
        self.ri = rag_indexer
        self.idx = rag_indexer.RagIndex()

    def test_stats_expose_cache_and_stamp(self):
        stats = self.idx.stats()
        self.assertIn(stats["cache"], ("hit", "built", "built+saved"))
        self.assertIn("stamp", stats)
        self.assertTrue(stats["stamp"][1])

    def test_cache_file_lives_outside_the_chain_dir(self):
        from app.config import CHAIN_DIR
        path = self.ri.cache_path(str(CHAIN_DIR), self.idx.stats()["embedder"],
                                  self.idx.stats()["dim"])
        self.assertFalse(str(path).startswith(str(CHAIN_DIR)))

    def test_second_index_reuses_cached_vectors(self):
        self.idx.ensure_ready()          # first build (may save)
        fresh = self.ri.RagIndex()
        fresh.ensure_ready()
        self.assertEqual(fresh.stats()["cache"], "hit")

    def test_cache_is_invalidated_when_chain_grows(self):
        from app import chain_service
        first = self.ri.RagIndex()
        first.ensure_ready()
        stamp_before = tuple(first.stats()["stamp"])
        entries_before = first.stats()["entries"]

        doc = json.loads(json.dumps(SAMPLE_DIPLOMA))
        doc["PersonalParticulars"]["StudentID"] = "55667788"
        chain_service.issue(doc)

        second = self.ri.RagIndex()
        stamp_after = second._current_stamp()
        self.assertNotEqual(stamp_after, stamp_before)
        second.ensure_ready()
        # Whatever served the vectors, they must belong to the new stamp, and
        # the corpus must include the block that was just appended.
        self.assertEqual(tuple(second.stats()["stamp"]), stamp_after)
        self.assertGreater(second.stats()["entries"], entries_before)

    def test_exact_hash_hit_outranks_vector_hits(self):
        from app.config import CHAIN_DIR
        corpus = self.ri.build_corpus(str(CHAIN_DIR))
        credential = next(e for e in corpus if e["kind"] == "credential")
        exact = [{"id": credential["id"]}]
        vectors = [{"id": "block-000000001"}, {"id": "chain:info"}]
        fused = self.ri.fuse_exact_and_vector(exact, vectors, 3)
        self.assertEqual(fused[0]["id"], credential["id"])

    def test_fusion_drops_duplicates_and_respects_k(self):
        fused = self.ri.fuse_exact_and_vector(
            [{"id": "a"}], [{"id": "a"}, {"id": "b"}, {"id": "c"}], 2)
        self.assertEqual([v["id"] for v in fused], ["a", "b"])

    def test_rerank_only_reorders(self):
        entries = [
            {"id": "x", "text": "issuing organization university of utopia"},
            {"id": "y", "text": "irrelevant filler words entirely"},
        ]
        before = {e["id"] for _, e in [(0.5, entries[0]), (0.5, entries[1])]}
        ranked = self.ri.rerank("university organization", [(0.5, entries[0]), (0.5, entries[1])])
        self.assertEqual({e["id"] for _, e in ranked}, before)
        self.assertEqual(ranked[0][1]["id"], "x")

    def test_lexical_overlap_is_bounded(self):
        self.assertEqual(self.ri.lexical_overlap("", "anything"), 0.0)
        self.assertEqual(self.ri.lexical_overlap("chain height", "chain height"), 1.0)
        self.assertGreater(self.ri.lexical_overlap("chain what", "the chain is here"), 0.0)

    def test_search_still_returns_view_shape(self):
        results = self.idx.search("chain height", k=3)
        self.assertTrue(results)
        for view in results:
            self.assertIn("id", view)
            self.assertIn("text", view)
            self.assertIn("score", view)

    def test_retrieval_text_never_carries_a_date_of_birth(self):
        """U5.3: the corpus is what the LLM reads — DOB must not be in it.

        The offline engine paraphrases and would hide it, but a real model
        quotes the context verbatim, so the DOB has to be absent from the
        indexed text itself rather than filtered out afterwards.
        """
        from app.config import CHAIN_DIR
        corpus = self.ri.build_corpus(str(CHAIN_DIR))
        credential_texts = [e["text"] for e in corpus if e["kind"] == "credential"]
        self.assertTrue(credential_texts, "demo chain should expose credentials")
        lowered = " ".join(credential_texts).lower()
        self.assertNotIn("date of birth", lowered)
        self.assertNotIn("dob", lowered)


class GeneratorContractTests(unittest.TestCase):
    """U5.2: structural validation, rule table, backend degradation chain."""

    def setUp(self):
        from app import chain_service, rag_generator
        chain_service.ensure_chain()
        self.rg = rag_generator
        self._saved = (rag_generator.DEEPSEEK_API_KEY, rag_generator.OLLAMA_BASE_URL)
        self.records = [{"id": "chain:info", "text": "chain height 2",
                         "kind": "chain", "score": 0.9}]

    def tearDown(self):
        self.rg.DEEPSEEK_API_KEY, self.rg.OLLAMA_BASE_URL = self._saved

    def test_validate_rejects_empty_answer(self):
        v = self.rg.validate_answer("   ", [1], 1)
        self.assertFalse(v["ok"])
        self.assertIn("answer is empty", v["problems"])

    def test_validate_drops_out_of_range_citation(self):
        v = self.rg.validate_answer("Chain has 2 blocks [7].", [7], 1)
        self.assertFalse(v["ok"])
        self.assertEqual(v["citations"], [])
        self.assertTrue(any("outside" in p for p in v["problems"]), v["problems"])

    def test_validate_allows_zero_citations_but_flags_it(self):
        v = self.rg.validate_answer("I cannot answer from the records.", [], 2)
        self.assertTrue(v["ok"])
        self.assertTrue(v["zero_citations"])
        self.assertIn("answer cites no record", v["problems"])

    def test_validate_keeps_valid_citations_and_dedupes(self):
        v = self.rg.validate_answer("answer [1][1][2]", [1, 1, 2], 3)
        self.assertTrue(v["ok"])
        self.assertEqual(v["citations"], [1, 2])

    def test_chain_wide_answer_never_cites_an_unrelated_credential(self):
        # The QA golden set (U5.4) caught this: chain-wide rules used to return
        # a hardcoded [1], which pointed at a credential whenever retrieval
        # ranked one first.
        from app.config import CHAIN_DIR
        records = [{"id": "credential:abc", "text": "credential text",
                    "kind": "credential"}]
        self.assertEqual(self.rg._chain_cite(records), [])
        answer, citations = self.rg._offline(
            "Who is the trusted signer of this chain?", records, str(CHAIN_DIR))
        self.assertEqual(citations, [])
        self.assertIn("signer", answer.lower())

    def test_chain_wide_answer_cites_chain_record_when_present(self):
        records = [{"id": "credential:abc", "text": "c", "kind": "credential"},
                   {"id": "chain:info", "text": "chain facts", "kind": "chain"}]
        self.assertEqual(self.rg._chain_cite(records), [2])

    def test_offline_rule_table_is_ordered_and_terminal(self):
        names = self.rg.offline_rule_names()
        self.assertEqual(names[0], "exact-hash")
        self.assertEqual(names[-1], "summary")
        self.assertIn("unknown-sid", names)

    def test_offline_answers_without_any_backend(self):
        self.rg.DEEPSEEK_API_KEY = None
        self.rg.OLLAMA_BASE_URL = None
        out = self.rg.generate("How many blocks are on the chain?", self.records)
        self.assertEqual(out["backend"], "offline")
        self.assertEqual(out["degraded"], [])
        self.assertTrue(out["answer"])
        self.assertTrue(out["validation"]["ok"])

    def test_deepseek_failure_degrades_to_offline_with_reason(self):
        self.rg.DEEPSEEK_API_KEY = "sk-fake"
        self.rg.OLLAMA_BASE_URL = None
        with mock.patch.object(self.rg, "_deepseek",
                                        side_effect=OSError("network down")):
            out = self.rg.generate("How many blocks are on the chain?", self.records)
        self.assertEqual(out["backend"], "offline")
        self.assertEqual(len(out["degraded"]), 1)
        self.assertIn("deepseek unavailable", out["degraded"][0])

    def test_deepseek_failure_then_ollama_succeeds(self):
        self.rg.DEEPSEEK_API_KEY = "sk-fake"
        self.rg.OLLAMA_BASE_URL = "http://127.0.0.1:11434"
        with mock.patch.object(self.rg, "_deepseek",
                                        side_effect=OSError("network down")), \
                mock.patch.object(self.rg, "_ollama",
                                           return_value=("Two blocks [1].", "qwen")):
            out = self.rg.generate("How many blocks are on the chain?", self.records)
        self.assertEqual(out["backend"], "ollama")
        self.assertEqual(out["model"], "qwen")
        self.assertEqual(out["citations"], [1])
        self.assertIn("deepseek unavailable", out["degraded"][0])

    def test_empty_llm_answer_falls_back_to_offline(self):
        self.rg.DEEPSEEK_API_KEY = "sk-fake"
        self.rg.OLLAMA_BASE_URL = None
        with mock.patch.object(self.rg, "_deepseek",
                                        return_value=("   ", "deepseek-chat")):
            out = self.rg.generate("How many blocks are on the chain?", self.records)
        self.assertEqual(out["backend"], "offline")
        self.assertTrue(out["answer"].strip())
        self.assertTrue(any("structural validation" in d for d in out["degraded"]))

    def test_llm_answer_with_fabricated_citation_is_discarded(self):
        self.rg.DEEPSEEK_API_KEY = "sk-fake"
        self.rg.OLLAMA_BASE_URL = None
        with mock.patch.object(self.rg, "_deepseek",
                                        return_value=("see [9]", "deepseek-chat")):
            out = self.rg.generate("How many blocks are on the chain?", self.records)
        self.assertEqual(out["backend"], "offline")
        self.assertLessEqual(max(out["citations"]), len(self.records))


if __name__ == "__main__":
    unittest.main()
