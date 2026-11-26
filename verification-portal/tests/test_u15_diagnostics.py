"""U15 diagnostics regression: uptime units, integrity surface, scan cache.

Three failures that are invisible until they are total:

    uptime_s      reported an epoch stamp, so every uptime check read ~1.7e9 s
    integrity     a chain with one untrusted historical signer made *every*
                  verdict INVALID, and nothing on /healthz said why
    scan cache    revoked_records() walked the whole chain on each call, and
                  batch verification calls it once per hash
"""

import unittest
from unittest import mock

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u15-test-",
    ADMIN_TOKEN="u15-admin-token",
    CAPABILITY_SECRET="u15-capability-secret",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import blockchain_util, chain_service, issuance_service  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class U15DiagnosticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)

    def test_uptime_is_seconds_not_an_epoch_stamp(self):
        body = self.client.get("/api/version").json()
        uptime = body["uptime_s"]
        self.assertIsInstance(uptime, (int, float))
        self.assertGreaterEqual(uptime, 0)
        # a wall-clock timestamp would be ~1.7e9; a year of uptime is 3.1e7
        self.assertLess(uptime, 365 * 24 * 3600)

    def test_healthz_reports_chain_integrity(self):
        body = self.client.get("/healthz").json()
        self.assertEqual(body["status"], "ok")
        integrity = body["checks"]["chain"]["integrity"]
        self.assertTrue(integrity["ok"])
        self.assertEqual(integrity["bad_blocks"], [])

    def test_version_reports_integrity_for_the_public_page(self):
        body = self.client.get("/api/version").json()
        integrity = body["chain"]["integrity"]
        self.assertTrue(integrity["ok"])
        self.assertEqual(integrity["bad_blocks"], [])

    def test_a_broken_chain_makes_healthz_degraded(self):
        # The real trigger (a block signed by a signer no longer in info.yaml)
        # is expensive to build; what matters here is the wiring: a false
        # integrity result must change the top-level status, not just a detail.
        with mock.patch.object(main, "chain_integrity",
                               return_value={"ok": False, "bad_blocks": [12]}):
            body = self.client.get("/healthz").json()
        self.assertEqual(body["status"], "degraded")
        self.assertFalse(body["checks"]["chain"]["integrity"]["ok"])
        self.assertEqual(body["checks"]["chain"]["integrity"]["bad_blocks"], [12])

    def test_revoked_records_scan_is_cached_per_height(self):
        calls = {"n": 0}
        real = blockchain_util.load_block

        def counting(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        issuance_service._revoked_cache = None
        with mock.patch.object(blockchain_util, "load_block", counting):
            first = issuance_service.revoked_records()
            second = issuance_service.revoked_records()
        height = blockchain_util.last_height(str(main.CHAIN_DIR))
        # one pass over the chain, not one per call
        self.assertGreater(calls["n"], 0)
        self.assertLessEqual(calls["n"], height)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
