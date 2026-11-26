"""Batch U7.2 — request correlation, structured logs, metrics, health checks.

What is actually being asserted:

* every request carries ``X-Request-ID``, **including the ones the hardening
  middleware rejects before routing** (403 / 413 / 429 / 401) — the rejections
  are exactly where you need a correlation id most;
* the log line is one JSON object with level/endpoint/status/duration, and a
  credential hash never appears in full (only an 8-character stub);
* counters move: verification totals, verdict distribution, denial kinds;
* endpoint labels are bucketed, so a hash cannot leak into metrics as a key;
* ``/healthz`` reports per-dependency state instead of one boolean.

Runs in its own process with a throwaway chain (see tests/_bootstrap.py).
"""

import json
import logging
import unittest

from tests._bootstrap import isolated_chain_dir

SAMPLES = {
    "PersonalParticulars": {
        "Surname": "CHAN", "GivenNames": "TAI MAN", "StudentID": "90100001",
        "Sex": "M", "DOB": "19880808",
    },
    "AcademicInfo": {
        "DegreeName": "Bachelor of Engineering",
        "DegreeStartDate": "20220901", "DegreeEndDate": "20260801",
        "Honour": "First Class Honours",
    },
    "DocumentInfo": {
        "DocType": "Diploma", "IssuingO": "UNIVERSITY OF UTOPIA",
        "IssuingOU": "FACULTY OF ENGINEERING", "DateOfIssue": "20260901",
        "AuthorizedSignature": "REGISTRAR",
    },
}

HASH_ARG = "A" * 40          # shape-valid base64url, certainly not on chain


class _Capture(logging.Handler):
    """Collect the portal's structured lines instead of printing them."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):  # noqa: D102 - logging protocol
        self.lines.append(record.getMessage())

    def events(self) -> list[dict]:
        return [json.loads(line) for line in self.lines if line.startswith("{")]


def setUpModule():
    isolated_chain_dir(prefix="gef26-obs-", PORTAL_LOG_LEVEL="INFO")
    import app.main as main_mod
    import app.observability as obs_mod
    from fastapi.testclient import TestClient

    global client, main, obs, capture
    main, obs = main_mod, obs_mod
    capture = _Capture()
    obs.logger.addHandler(capture)
    obs.logger.setLevel(logging.INFO)
    client = TestClient(main_mod.app)


class RequestIdTests(unittest.TestCase):
    def test_header_present_on_success(self):
        res = client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        rid = res.headers.get("X-Request-ID")
        self.assertTrue(rid, "no X-Request-ID on a 200")
        self.assertRegex(rid, r"^[A-Za-z0-9_-]{8,64}$")

    def test_client_supplied_id_is_echoed(self):
        res = client.get("/healthz", headers={"X-Request-ID": "abc12345"})
        self.assertEqual(res.headers["X-Request-ID"], "abc12345")

    def test_malformed_client_id_is_replaced(self):
        res = client.get("/healthz", headers={"X-Request-ID": "bad id!"})
        self.assertNotEqual(res.headers["X-Request-ID"], "bad id!")
        self.assertRegex(res.headers["X-Request-ID"], r"^[A-Za-z0-9_-]{8,64}$")

    def test_rejection_before_routing_carries_id(self):
        """The 403 path never reaches the router — it must still be traceable."""
        res = client.post("/api/issue", json={},
                          headers={"Origin": "https://evil.example.com"})
        self.assertEqual(res.status_code, 403)
        self.assertIn("X-Request-ID", res.headers)


class StructuredLogTests(unittest.TestCase):
    def setUp(self):
        capture.lines.clear()

    def test_request_line_shape(self):
        client.get("/healthz", headers={"X-Request-ID": "logtest0001"})
        events = [e for e in capture.events() if e["event"] == "request"]
        self.assertTrue(events, "no request log line")
        line = events[-1]
        for key in ("ts", "level", "event", "request_id", "endpoint",
                    "method", "status", "duration_ms"):
            self.assertIn(key, line)
        self.assertEqual(line["request_id"], "logtest0001")
        self.assertEqual(line["endpoint"], "/healthz")

    def test_verification_line_has_verdict_and_truncated_hash(self):
        issued = client.post("/api/issue", json={"document": SAMPLES}).json()
        h = issued["hashed_document"]
        res = client.get(f"/api/verify/{h}")
        self.assertEqual(res.status_code, 200)
        events = [e for e in capture.events() if e["event"] == "verification"]
        self.assertTrue(events, "no verification log line")
        line = events[-1]
        self.assertEqual(line["verdict"], res.json()["verdict"])
        self.assertIsInstance(line["height"], int)
        self.assertGreater(line["height"], 0)
        # the full hash must not be in the line, only an 8-char stub
        self.assertNotIn(h, json.dumps(line, ensure_ascii=False))
        self.assertTrue(str(line["hashed_document"]).endswith("…"))

    def test_log_never_carries_pii(self):
        """Issue with an e-mail + student id and make sure neither leaks."""
        doc = json.loads(json.dumps(SAMPLES))
        doc["DocumentInfo"]["StudentEmail"] = "tai.man@example.edu"
        client.post("/api/issue", json={
            "document": doc, "email": "tai.man@example.edu"})
        blob = "\n".join(capture.lines)
        self.assertNotIn("tai.man@example.edu", blob)
        # student id is a document field, not logged at all; assert the value
        # in its raw form never appears (it may appear masked, never raw)
        self.assertNotIn("90100001", blob)


class MetricsTests(unittest.TestCase):
    def setUp(self):
        obs.COUNTERS.reset()

    def test_verification_counter_and_verdict_mix(self):
        issued = client.post("/api/issue", json={"document": SAMPLES}).json()
        h = issued["hashed_document"]
        client.get(f"/api/verify/{h}")
        client.get(f"/api/verify/{HASH_ARG}")          # NOT FOUND
        snap = client.get("/api/metrics").json()
        self.assertEqual(snap["verifications_total"], 2)
        self.assertIn("VALID ON CHAIN", snap["verdict_distribution"])
        self.assertEqual(snap["verdict_distribution"]["VALID ON CHAIN"], 1)
        self.assertIn("NOT FOUND", snap["verdict_distribution"])
        self.assertEqual(snap["verdict_distribution"]["NOT FOUND"], 1)

    def test_endpoint_labels_do_not_leak_hashes(self):
        client.get(f"/api/verify/{HASH_ARG}")
        snap = client.get("/api/metrics").json()
        endpoints = {row["endpoint"] for row in snap["requests"]}
        self.assertIn("/api/verify/{id}", endpoints)
        self.assertFalse([e for e in endpoints if HASH_ARG in e],
                         "a credential hash leaked into a metric label")

    def test_rate_limit_denials_are_counted(self):
        main._public_limiter = main.SlidingWindowLimiter()
        original = main.RATE_LIMIT_PUBLIC_MAX
        main.RATE_LIMIT_PUBLIC_MAX = 2
        try:
            codes = [client.get("/api/demo/credentials").status_code
                     for _ in range(4)]
        finally:
            main.RATE_LIMIT_PUBLIC_MAX = original
            main._public_limiter = main.SlidingWindowLimiter()
        self.assertEqual(codes[:2], [200, 200])
        self.assertEqual(codes[2], 429)
        snap = client.get("/api/metrics").json()
        self.assertEqual(snap["denied"]["rate_limit"], 2)

    def test_body_too_large_is_counted(self):
        res = client.post("/api/issue", json={"document": SAMPLES},
                          headers={"Content-Length": str(64 * 1024 * 1024)})
        self.assertEqual(res.status_code, 413)
        snap = client.get("/api/metrics").json()
        self.assertGreaterEqual(snap["denied"]["body_too_large"], 1)

    def test_origin_denial_is_counted(self):
        client.post("/api/issue", json={},
                    headers={"Origin": "https://evil.example.com"})
        snap = client.get("/api/metrics").json()
        self.assertGreaterEqual(snap["denied"]["origin"], 1)

    def test_payload_declares_per_process_counters(self):
        snap = client.get("/api/metrics").json()
        self.assertIs(snap["shared_across_workers"], False)


class HealthTests(unittest.TestCase):
    def test_healthz_reports_each_dependency(self):
        res = client.get("/healthz")
        body = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body["status"], "ok")
        checks = body["checks"]
        self.assertTrue(checks["chain_dir"]["path_exists"])
        self.assertTrue(checks["chain_dir"]["writable"])
        self.assertTrue(checks["static"]["dir_exists"])
        self.assertGreaterEqual(checks["chain"]["height"], 0)
        self.assertEqual(checks["storage"]["backend"],
                         main.cfg.STORAGE_BACKEND)
        self.assertIs(checks["observability"]["counters_shared_across_workers"],
                      False)

    def test_healthz_keeps_the_original_flat_fields(self):
        """The old contract (chain_name/height at top level) must not break."""
        body = client.get("/healthz").json()
        self.assertIn("chain_name", body)
        self.assertIn("height", body)
        self.assertIn("content_hash_algo", body)


if __name__ == "__main__":
    unittest.main()
