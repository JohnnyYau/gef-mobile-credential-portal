"""U24 — X-Forwarded-For is only believed when the peer is a trusted proxy.

U16 unified the two rate-limit keys on ``_client_ip()`` so that one reverse
proxy would not turn every browser into the same bucket. The same function
read ``X-Forwarded-For`` unconditionally, which handed the bypass back to the
caller: on a portal with no proxy in front, ``curl -H 'X-Forwarded-For: <any
address>'`` produced a brand-new bucket per request, so both limiters (and the
login lockout) could be walked past for free. Worse, a fixed forged address
shut *someone else's* bucket.

The header is now read only when the direct peer is listed in
``TRUSTED_PROXIES``. Empty (the default) means it is ignored entirely.
"""

import ipaddress
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u24-",
    ADMIN_TOKEN="u24-admin-token",
    DEMO_OPEN="0",
    PUBLIC_MODE="0",
)

import app.main as main  # noqa: E402
from app import chain_service  # noqa: E402
from app import startup  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402


def _request(peer, xff=None) -> Request:
    """A minimal ASGI request with a chosen peer address and X-Forwarded-For."""
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/healthz", "raw_path": b"/healthz",
        "query_string": b"", "root_path": "",
        "headers": headers,
        "client": (peer, 43210) if peer is not None else None,
        "server": ("testserver", 80),
    }
    return Request(scope)


class ClientIpTest(unittest.TestCase):
    def setUp(self):
        self._original = main.cfg.TRUSTED_PROXIES
        main.cfg.TRUSTED_PROXIES = ""
        self.addCleanup(setattr, main.cfg, "TRUSTED_PROXIES", self._original)

    def _trust(self, value: str):
        main.cfg.TRUSTED_PROXIES = value

    # ---- the safe default -------------------------------------------------

    def test_forged_header_is_ignored_by_default(self):
        self.assertEqual(main._client_ip(_request("198.51.100.5", "203.0.113.9")),
                         "198.51.100.5",
                         "with no trusted proxy, X-Forwarded-For must not pick the bucket")

    def test_a_fresh_forgery_per_request_does_not_mint_buckets(self):
        keys = {main._client_ip(_request("198.51.100.5", f"203.0.113.{i}"))
                for i in range(5)}
        self.assertEqual(keys, {"198.51.100.5"})

    def test_non_ip_peer_still_ignores_the_header(self):
        # TestClient's own peer name; also stands in for anything unparseable.
        self.assertEqual(main._client_ip(_request("testclient", "203.0.113.9")),
                         "testclient")

    # ---- behind a proxy, when the peer is trusted -------------------------

    def test_trusted_peer_is_believed(self):
        self._trust("127.0.0.1")
        self.assertEqual(main._client_ip(_request("127.0.0.1", "203.0.113.9")),
                         "203.0.113.9")

    def test_cidr_is_understood(self):
        self._trust("10.0.0.0/8")
        self.assertEqual(main._client_ip(_request("10.1.2.3", "203.0.113.9")),
                         "203.0.113.9")

    def test_the_nearest_untrusted_hop_is_the_client(self):
        # A caller may write anything on the left; the rightmost hop that is
        # not itself a trusted proxy is the one that actually reached us.
        self._trust("127.0.0.1,10.0.0.0/8")
        self.assertEqual(
            main._client_ip(_request("127.0.0.1", "1.1.1.1, 203.0.113.9, 10.0.0.7")),
            "203.0.113.9")

    def test_all_hops_trusted_falls_back_to_the_leftmost(self):
        self._trust("127.0.0.1,10.0.0.0/8")
        self.assertEqual(main._client_ip(_request("127.0.0.1", "10.0.0.7, 10.0.0.8")),
                         "10.0.0.7")

    def test_an_untrusted_peer_cannot_claim_to_be_a_proxy(self):
        # 198.51.100.5 is not in the list, so it is the client — whatever it says.
        self._trust("127.0.0.1")
        self.assertEqual(main._client_ip(_request("198.51.100.5", "203.0.113.9")),
                         "198.51.100.5")

    def test_blank_header_falls_back_to_the_peer(self):
        self._trust("127.0.0.1")
        for header in ("", "   ", ",", " , "):
            self.assertEqual(main._client_ip(_request("127.0.0.1", header)),
                             "127.0.0.1")

    def test_no_client_in_scope_is_unknown_not_trusted(self):
        self.assertEqual(main._client_ip(_request(None, "203.0.113.9")), "unknown")

    # ---- bad configuration is loud, and fails closed ---------------------

    def test_invalid_entry_trusts_nothing_and_is_named(self):
        self._trust("not-an-ip")
        nets, bad = main._proxy_nets()
        self.assertEqual(nets, [])
        self.assertEqual(bad, ["not-an-ip"])
        self.assertEqual(main._client_ip(_request("127.0.0.1", "203.0.113.9")),
                         "127.0.0.1")

    def test_startup_warns_about_the_invalid_entry(self):
        original = main.cfg.TRUSTED_PROXIES

        class C:
            pass

        for name in ("STORAGE_BACKEND", "CHAIN_DIR", "SQLITE_PATH", "STATIC_DIR",
                     "SESSION_BACKEND", "PUBLIC_MODE", "ADMIN_TOKEN",
                     "EMAIL_ENABLED", "SIGNER_KEY_PASSPHRASE",
                     "CHAIN_SNAPSHOT_URL", "RATE_LIMIT_ENABLED",
                     "RATE_LIMIT_PUBLIC_MAX", "RATE_LIMIT_ADMIN_MAX",
                     "ALLOWED_ORIGINS", "PUBLIC_BASE_URL"):
            setattr(C, name, getattr(main.cfg, name))
        C.TRUSTED_PROXIES = "127.0.0.1, oops"
        report = startup.validate_config(C)
        self.assertTrue(any("TRUSTED_PROXIES" in w for w in report["warnings"]),
                        report["warnings"])
        self.assertEqual(main.cfg.TRUSTED_PROXIES, "")  # validate_config mutates nothing


class ProxyTrustSurfaceTest(unittest.TestCase):
    """The two operator-facing surfaces must say which address they bucket on."""

    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)
        cls.admin = {"X-Admin-Token": "u24-admin-token"}
        cls._saved_admins = main.RATE_LIMIT_ADMIN_MAX
        main.RATE_LIMIT_ADMIN_MAX = 100000

    @classmethod
    def tearDownClass(cls):
        main.RATE_LIMIT_ADMIN_MAX = cls._saved_admins

    def setUp(self):
        self._original = main.cfg.TRUSTED_PROXIES
        main.cfg.TRUSTED_PROXIES = ""
        self.addCleanup(setattr, main.cfg, "TRUSTED_PROXIES", self._original)

    def test_healthz_says_the_header_is_ignored(self):
        body = self.client.get("/healthz").json()
        self.assertEqual(body["checks"]["observability"]["client_ip_source"], "peer")

    def test_healthz_says_the_header_is_used_behind_a_proxy(self):
        main.cfg.TRUSTED_PROXIES = "127.0.0.1"
        body = self.client.get("/healthz").json()
        self.assertEqual(body["checks"]["observability"]["client_ip_source"],
                         "x-forwarded-for")

    def test_diagnostics_lists_the_trusted_proxies(self):
        main.cfg.TRUSTED_PROXIES = "127.0.0.1,10.0.0.0/8"
        body = self.client.get("/api/diagnostics", headers=self.admin).json()
        block = body["client_ip"]
        self.assertEqual(block["source"], "x-forwarded-for")
        self.assertEqual(block["trusted_proxies"],
                         ["127.0.0.1/32", "10.0.0.0/8"])
        self.assertEqual(block["invalid_entries"], [])

    def test_public_surface_stays_small(self):
        body = self.client.get("/healthz").json()
        self.assertNotIn("client_ip", body)
        self.assertNotIn("trusted_proxies", str(body))


class ForgedHeaderCannotBypassTheLoginLockoutTest(unittest.TestCase):
    """End-to-end: five bad tokens lock the bucket, whatever the header says."""

    @classmethod
    def setUpClass(cls):
        chain_service.ensure_chain()
        cls.client = TestClient(main.app)

    def setUp(self):
        self._original = main.cfg.TRUSTED_PROXIES
        main.cfg.TRUSTED_PROXIES = ""
        self.addCleanup(setattr, main.cfg, "TRUSTED_PROXIES", self._original)
        main.authz.clear_login_failures("testclient")

    def test_five_failures_lock_the_peer_even_with_rotating_headers(self):
        for i in range(5):
            resp = self.client.post("/staff/login",
                                    json={"token": "wrong"},
                                    headers={"X-Forwarded-For": f"203.0.113.{i}"})
            self.assertEqual(resp.status_code, 401, resp.text)
        # The sixth attempt carries yet another address: it must still be
        # refused, because the bucket is the peer, not the header.
        resp = self.client.post("/staff/login",
                                json={"token": "wrong"},
                                headers={"X-Forwarded-For": "198.51.100.77"})
        self.assertEqual(resp.status_code, 429, resp.text)
        self.assertIn("Retry-After", resp.headers)


if __name__ == "__main__":
    unittest.main()
