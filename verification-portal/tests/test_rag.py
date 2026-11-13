"""RAG chat tests (Week 2): retrieval + chat endpoint + offline generator.

Uses an isolated chain; no API keys set, so the offline generator answers.
If sentence-transformers cannot load (no network for the model download) the
embedder falls back to hashing — retrieval tests still hold because query and
corpus share name/ID tokens.
"""

import json
import os
import shutil
import tempfile
import unittest

# Isolated chain + force the offline generator (must precede app import).
_TMP = tempfile.mkdtemp(prefix="portal-rag-test-")
os.environ["CHAIN_DIR"] = os.path.join(_TMP, "test-chain")
os.environ.pop("DEEPSEEK_API_KEY", None)
os.environ.pop("OLLAMA_BASE_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402
from app.main import app  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
