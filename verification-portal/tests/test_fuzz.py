"""Batch U7.1 — hostile input, no crashes.

Every case here is a shape a fuzzer would find and a reviewer would not
hand-write: truncated PDFs, binary junk with a fake header, JSON wedged into
nested lists, wrong types in every field, oversized documents, malformed
hashes, batch payloads that are objects where arrays belong.

The contract is narrow and deliberate: **no 5xx, no traceback in the body**.
The endpoints are allowed to say 422/415/413/400/200 — an input problem is
the caller's, not an internal error. A 500 means an unhandled exception
escaped, which is exactly what this module exists to catch.

Rate limiting is off for this module: a 429 would mask the parsing behaviour
under test without telling us anything about it.
"""

import random
import unittest
from urllib.parse import quote

from tests._bootstrap import isolated_chain_dir

SEED = 20261113


def setUpModule():
    isolated_chain_dir(prefix="gef26-fuzz-", RATE_LIMIT_ENABLED="0")
    from app.main import app as _app
    from fastapi.testclient import TestClient
    global client
    client = TestClient(_app, raise_server_exceptions=False)


def _ok(testcase, res, label: str) -> None:
    testcase.assertLess(res.status_code, 500,
                        f"{label}: {res.status_code} {res.text[:200]}")
    testcase.assertNotIn("Traceback", res.text, f"{label}: traceback leaked")


PDFISH = [
    b"",
    b"%PDF",
    b"%PDF-1.7",
    b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n",
    b"not a pdf at all",
    b"%PDF" + b"\x00" * 64,
    b"%PDF-1.4\n" + bytes(range(256)) * 4,
    b"\xff\xd8\xff\xe0" + b"A" * 512,          # a JPEG pretending to be a draft
    b"%PDF-1.7\n%%EOF\n" + b"trailing garbage",
]


class FuzzPdfTests(unittest.TestCase):
    def test_extract_pdf_survives_junk(self):
        for i, blob in enumerate(PDFISH):
            res = client.post(
                "/api/extract/pdf",
                files={"file": (f"fuzz{i}.pdf", blob, "application/pdf")})
            _ok(self, res, f"extract/pdf #{i}")

    def test_verify_document_pdf_survives_junk(self):
        for i, blob in enumerate(PDFISH):
            res = client.post(
                "/api/verify/document",
                files={"file": (f"fuzz{i}.pdf", blob, "application/pdf")})
            _ok(self, res, f"verify/document pdf #{i}")

    def test_random_binary_bodies(self):
        rng = random.Random(SEED)
        for i in range(12):
            blob = bytes(rng.getrandbits(8) for _ in range(rng.randint(1, 600)))
            res = client.post(
                "/api/extract/pdf",
                files={"file": (f"rand{i}.bin", blob, "application/octet-stream")})
            _ok(self, res, f"random binary #{i}")


WRONG_TYPES = [
    "a string",
    42,
    3.5,
    None,
    True,
    [],
    [1, 2, 3],
    ["a", ["b", ["c"]]],
]


class FuzzDocumentShapeTests(unittest.TestCase):
    def test_wrong_top_level_types(self):
        for i, value in enumerate(WRONG_TYPES):
            res = client.post("/api/issue", json={"document": value})
            _ok(self, res, f"issue document={type(value).__name__}#{i}")

    def test_missing_and_mistyped_sections(self):
        for payload in (
            {},
            {"document": {}},
            {"document": {"PersonalParticulars": "x"}},
            {"document": {"PersonalParticulars": {"Surname": ["LIST"]}}},
            {"document": {"AcademicInfo": 1, "DocumentInfo": None}},
            {"document": {"PersonalParticulars": {}, "AcademicInfo": {},
                          "DocumentInfo": {}}},
        ):
            res = client.post("/api/issue", json=payload)
            _ok(self, res, "issue mistyped sections")

    def test_deep_nesting_is_rejected_without_crashing(self):
        deep: dict = {}
        cursor = deep
        for _ in range(80):                    # over MAX_JSON_DEPTH (50)
            cursor["next"] = {}
            cursor = cursor["next"]
        res = client.post("/api/issue", json={"document": {"Deep": deep}})
        _ok(self, res, "deep nesting")
        self.assertEqual(res.status_code, 422)

    def test_oversized_document_is_rejected(self):
        blob = "x" * (3 * 1024 * 1024)         # over MAX_JSON_BYTES (2 MB)
        res = client.post("/api/issue", json={"document": {"Blob": blob}})
        _ok(self, res, "oversized document")

    def test_wrong_content_type(self):
        for ctype in ("text/plain", "application/xml", ""):
            res = client.post("/api/verify/document", content=b"{}",
                              headers={"Content-Type": ctype} if ctype else {})
            _ok(self, res, f"verify/document ctype={ctype!r}")

    def test_malformed_json_body(self):
        for body in (b"{", b"[]", b'"str"', b"null", b'{"document": }'):
            res = client.post("/api/verify/document", content=body,
                              headers={"Content-Type": "application/json"})
            _ok(self, res, "malformed json")


HASHISH = [
    "", "a", "A" * 15, "A" * 16, "A" * 200, "A" * 201,
    "=" * 24, "a+b/c", "../" + "A" * 20, "A" * 40 + "%00",
    "哈希" * 10, "  " + "A" * 20, "A" * 40 + "\n", "null",
    "0" * 44, "-" * 40, "A" * 40 + ".json", "%2e%2e%2f" + "A" * 20,
]


class FuzzHashTests(unittest.TestCase):
    def test_hash_endpoints_survive_junk(self):
        for i, value in enumerate(HASHISH):
            # percent-encode so control characters / spaces reach the app as a
            # legal URL instead of being rejected by the client (that tests
            # httpx, not the portal)
            quoted = quote(value, safe="")
            res = client.get(f"/api/verify/{quoted}")
            _ok(self, res, f"verify hash #{i}")
            res2 = client.get(f"/api/status/{quoted}")
            _ok(self, res2, f"status hash #{i}")
            res3 = client.get(f"/api/pdf/{quoted}")
            _ok(self, res3, f"pdf hash #{i}")

    def test_batch_accepts_any_shape_without_crashing(self):
        for payload in (
            {},
            {"hashes": "not-a-list"},
            {"hashes": [None, 1, True, {}, []]},
            {"hashes": ["A" * 40] * 3},
            {"hashes": list(range(50))},
            {"hashes": ["a" * 40 + "\n"]},
        ):
            res = client.post("/api/verify/batch", json=payload,
                              headers={"Content-Type": "application/json"})
            _ok(self, res, "batch shape")
            self.assertIn(res.status_code, (200, 422), res.text[:120])

    def test_disclosure_survives_junk(self):
        for payload in ({}, {"credential_hash": "x"},
                        {"credential_hash": "A" * 40, "sections": 5}):
            res = client.post("/api/disclose/" + "A" * 40, json=payload)
            _ok(self, res, "disclose shape")
        for payload in ({}, {"credential_hash": 1},
                        {"credential_hash": "A" * 40, "sections": "no"}):
            res = client.post("/api/verify/disclosure", json=payload)
            _ok(self, res, "verify/disclosure shape")

    def test_chat_survives_junk_questions(self):
        for question in ("", "?", "\x00" * 3, "A" * 4000, "<script>alert(1)</script>"):
            res = client.post("/api/chat", json={"question": question})
            _ok(self, res, "chat junk question")


if __name__ == "__main__":
    unittest.main()
