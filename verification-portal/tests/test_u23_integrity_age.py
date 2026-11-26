"""U23 — a cached verdict has to say how old it is.

``chain_integrity()`` re-checks the whole chain at most every 30 s (U15), and
both ``/healthz`` and ``/api/version`` published the result as if it were live.
A block can be added, or a signer retired, and for up to half a minute every
surface still reports the old answer with no hint that it is old.

``checked_at`` (epoch seconds) and ``age_s`` now travel with the verdict. Callers
that only need the answer keep reading ``ok`` / ``bad_blocks``; the PDF renderer
and the tests did exactly that, so nothing else changed.

This module also checks the two places a deployment actually looks: the public
``/healthz`` block and the staff-only ``/api/diagnostics``.
"""

import time
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u23-",
    ADMIN_TOKEN="u23-admin-token",
    CAPABILITY_SECRET="u23-capability-secret",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import chain_service  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class IntegrityAgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls.h = {"X-Admin-Token": "u23-admin-token"}
        cls._saved_admin = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_ADMIN_MAX = 100000

    @classmethod
    def tearDownClass(cls):
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admin

    def setUp(self):
        # A fresh scan for every test, so the cache state is known.
        main._integrity_cache.update({"dir": None, "height": None, "ts": 0.0,
                                      "ok": None, "bad": []})

    # ---- the function itself ------------------------------------------
    def test_the_verdict_carries_when_it_was_computed(self):
        result = main.chain_integrity()
        self.assertIn("checked_at", result)
        self.assertIn("age_s", result)
        self.assertIsInstance(result["checked_at"], (int, float))
        self.assertGreaterEqual(result["age_s"], 0.0)
        self.assertIsInstance(result["ok"], bool)

    def test_a_cache_hit_keeps_the_original_timestamp(self):
        first = main.chain_integrity()
        second = main.chain_integrity()
        self.assertEqual(first["checked_at"], second["checked_at"],
                         "a cached verdict must not pretend to be a new scan")
        self.assertGreaterEqual(second["age_s"], first["age_s"])

    def test_a_stale_cache_is_recomputed(self):
        main.chain_integrity()
        height = main.blockchain_util.last_height(str(main.CHAIN_DIR))
        stale_ts = time.time() - (main._INTEGRITY_TTL + 50)
        main._integrity_cache.update({"dir": str(main.CHAIN_DIR), "height": height,
                                      "ts": stale_ts, "ok": True, "bad": []})
        later = main.chain_integrity()
        # The recomputed timestamp is a fresh scan, not the stale one.
        self.assertGreater(later["checked_at"], stale_ts + 40)
        self.assertLess(later["age_s"], 5.0)

    def test_the_result_is_json_safe(self):
        result = main.chain_integrity()
        import json
        json.dumps(result)  # must not raise: it goes straight into two endpoints

    # ---- the two surfaces ---------------------------------------------
    def test_healthz_publishes_the_age(self):
        main.chain_integrity()  # warm the cache
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        block = res.json()["checks"]["chain"]["integrity"]
        self.assertIn("checked_at", block)
        self.assertIn("age_s", block)

    def test_diagnostics_publishes_the_age(self):
        main.chain_integrity()
        res = self.client.get("/api/diagnostics", headers=self.h)
        self.assertEqual(res.status_code, 200, res.text)
        block = res.json()["chain"]["integrity"]
        self.assertIn("checked_at", block)
        self.assertIsInstance(block["age_s"], (int, float))

    def test_the_public_block_stays_counts_only(self):
        """U19's split must survive: no config text on the public endpoint."""
        res = self.client.get("/healthz")
        cfg = res.json()["checks"]["config"]
        self.assertIsInstance(cfg["warnings"], int)
        self.assertIsInstance(cfg["fatal"], int)

    def test_a_broken_chain_still_reports_a_time(self):
        main._integrity_cache.update({"dir": str(main.CHAIN_DIR),
                                      "height": main.blockchain_util.last_height(
                                          str(main.CHAIN_DIR)),
                                      "ts": time.time() - 1.0, "ok": False, "bad": [12]})
        result = main.chain_integrity()
        self.assertFalse(result["ok"])
        self.assertEqual(result["bad_blocks"], [12])
        self.assertGreater(result["age_s"], 0.9,
                           "a one-second-old cached verdict should read as aged")


if __name__ == "__main__":
    unittest.main()
