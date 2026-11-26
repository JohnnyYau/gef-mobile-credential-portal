"""Batch U8.2 — boot configuration validation and graceful shutdown.

`validate_config()` is pure: it takes a config-shaped object, so every branch
can be exercised without reloading the app. The point of the split is that a
*bad* setting must say so at boot, with the name of the variable, instead of
turning into a puzzling runtime symptom:

* fatal — the process cannot serve correct answers (unknown storage backend,
  unwritable chain/SQLite parent).
* warning — it can serve, but one capability is degraded; the operator is told
  which (`EMAIL_ENABLED` without `SMTP_HOST`, redis session placeholder,
  an empty ALLOWED_ORIGINS on a public URL, ...).

Also covered: shutdown drops the cached store bundle (`repository.close_all`)
and `/healthz` reports the config verdict so a deployed instance is checkable
after the fact rather than only in the boot log.
"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests._bootstrap import isolated_chain_dir


def _cfg(**overrides) -> SimpleNamespace:
    """A config object that validates clean, then apply the case's overrides."""
    base = dict(
        STORAGE_BACKEND="json",
        CHAIN_DIR=Path(os.environ["CHAIN_DIR"]),
        SQLITE_PATH=Path(tempfile.gettempdir()) / "gef26-u82" / "portal.sqlite3",
        STATIC_DIR=Path(__file__).resolve().parent.parent / "static",
        SESSION_BACKEND="memory",
        PUBLIC_MODE=False,
        ADMIN_TOKEN="",
        EMAIL_ENABLED=False,
        SMTP_HOST="",
        CHAIN_SNAPSHOT_URL="",
        RATE_LIMIT_ENABLED=True,
        RATE_LIMIT_PUBLIC_MAX=60,
        RATE_LIMIT_ADMIN_MAX=20,
        ALLOWED_ORIGINS="",
        PUBLIC_BASE_URL="http://127.0.0.1:8000",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def setUpModule():
    isolated_chain_dir(prefix="gef26-u82-")
    import app.startup as startup_mod
    global startup
    startup = startup_mod


class ConfigValidationTests(unittest.TestCase):
    def test_clean_config_has_no_fatal_and_no_warning(self):
        report = startup.validate_config(_cfg())
        self.assertEqual(report["fatal"], [])
        self.assertEqual(report["warnings"], [])

    def test_unknown_storage_backend_is_fatal(self):
        report = startup.validate_config(_cfg(STORAGE_BACKEND="sqlitee"))
        self.assertEqual(len(report["fatal"]), 1)
        self.assertIn("STORAGE_BACKEND", report["fatal"][0])

    def test_sqlite_with_unwritable_parent_is_fatal(self):
        blocker = Path(tempfile.mkdtemp(prefix="gef26-u82-file-")) / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        report = startup.validate_config(_cfg(
            STORAGE_BACKEND="sqlite",
            SQLITE_PATH=blocker / "nested" / "portal.sqlite3"))
        self.assertTrue(any("SQLITE_PATH" in line for line in report["fatal"]))

    def test_missing_static_dir_is_a_warning_not_fatal(self):
        report = startup.validate_config(_cfg(STATIC_DIR=Path("/nonexistent/static")))
        self.assertEqual(report["fatal"], [])
        self.assertTrue(any("STATIC_DIR" in line for line in report["warnings"]))

    def test_redis_session_backend_is_flagged_as_placeholder(self):
        report = startup.validate_config(_cfg(SESSION_BACKEND="redis"))
        self.assertTrue(any("redis" in line.lower() for line in report["warnings"]))

    def test_public_mode_with_admin_token_warns(self):
        report = startup.validate_config(_cfg(PUBLIC_MODE=True, ADMIN_TOKEN="t0ken"))
        self.assertTrue(any("ADMIN_TOKEN" in line for line in report["warnings"]))

    def test_email_without_smtp_host_warns(self):
        report = startup.validate_config(_cfg(EMAIL_ENABLED=True))
        self.assertTrue(any("SMTP_HOST" in line for line in report["warnings"]))

    def test_snapshot_url_with_existing_chain_warns(self):
        chain = Path(os.environ["CHAIN_DIR"])
        chain.mkdir(parents=True, exist_ok=True)
        (chain / "info.yaml").write_text("x: 1\n", encoding="utf-8")
        report = startup.validate_config(_cfg(CHAIN_SNAPSHOT_URL="https://x/snap.tar.gz"))
        self.assertTrue(any("CHAIN_SNAPSHOT_URL" in line for line in report["warnings"]))

    def test_zero_rate_limits_warn(self):
        report = startup.validate_config(_cfg(
            RATE_LIMIT_PUBLIC_MAX=0, RATE_LIMIT_ADMIN_MAX=0))
        self.assertTrue(any("RATE_LIMIT" in line for line in report["warnings"]))

    def test_public_https_without_origins_warns(self):
        report = startup.validate_config(
            _cfg(PUBLIC_BASE_URL="https://portal.example.com"))
        self.assertTrue(any("ALLOWED_ORIGINS" in line for line in report["warnings"]))

    def test_bad_log_level_warns(self):
        os.environ["PORTAL_LOG_LEVEL"] = "LOUD"
        try:
            report = startup.validate_config(_cfg())
        finally:
            os.environ["PORTAL_LOG_LEVEL"] = "WARNING"
        self.assertTrue(any("PORTAL_LOG_LEVEL" in line for line in report["warnings"]))

    def test_describe_formats_both_levels(self):
        lines = startup.describe({"fatal": ["a"], "warnings": ["b", "c"]}).splitlines()
        self.assertEqual(lines, ["fatal: a", "warning: b", "warning: c"])


class LifespanGateTests(unittest.TestCase):
    def test_fatal_config_refuses_to_start(self):
        """A non-implemented backend must stop the boot, not silently degrade."""
        import asyncio

        import app.config as cfg_mod
        import app.main as main_mod
        original = cfg_mod.STORAGE_BACKEND
        cfg_mod.STORAGE_BACKEND = "sqlitee"
        try:
            async def run():
                async with main_mod._lifespan(main_mod.app):
                    self.fail("lifespan served a mis-configured app")

            with self.assertRaises(RuntimeError) as caught:
                asyncio.run(run())
        finally:
            cfg_mod.STORAGE_BACKEND = original
        self.assertIn("STORAGE_BACKEND", str(caught.exception))


class ShutdownTests(unittest.TestCase):
    def test_close_all_clears_the_bundle_cache(self):
        from app import repository
        repository.store("api_keys")             # populate the cache
        self.assertEqual(repository.close_all(), 1)
        first = repository.store("api_keys")
        self.assertIsNotNone(first)               # rebuilt after the close
        self.assertEqual(repository.close_all(), 1)

    def test_repository_close_is_a_noop_on_the_json_backend(self):
        from app import repository
        bundle = repository._bundle_for("json")   # the bundle, not one store
        self.assertEqual(bundle.close(), 0)
        self.assertEqual(bundle.backend, "json")


class HealthzConfigTests(unittest.TestCase):
    def test_healthz_reports_config_counters(self):
        import app.main as main_mod
        from fastapi.testclient import TestClient
        with TestClient(main_mod.app) as client:
            payload = client.get("/healthz").json()
        self.assertIn("config", payload["checks"])
        self.assertEqual(payload["checks"]["config"]["fatal"], 0)
        self.assertIsInstance(payload["checks"]["config"]["warnings"], int)


if __name__ == "__main__":
    unittest.main()
