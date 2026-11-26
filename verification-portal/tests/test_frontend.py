"""U6 — frontend engineering: split shell, static mount, JS syntax, escaping.

Three layers, cheapest first:

1. the shell must stay a shell (no inline script bodies, assets referenced);
2. the server must actually serve those assets (`/static/...` was never
   mounted before the split — the page was self-contained);
3. the escaping suite in `tests/frontend/` must pass *and* must fail when a
   fix is reverted, so a green run is not vacuous.

Node is optional: without it the JS-execution tests skip, and the reason is
printed. They never silently pass.
"""

import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
FRONTEND = Path(__file__).resolve().parent / "frontend"

NODE_CANDIDATES = [
    os.environ.get("NODE_BIN", ""),
    shutil.which("node") or "",
    r"C:\Users\johnn\AppData\Local\Doubao\User Data\sandbox_runtime\bases"
    r"\fa694f517e5995233c80a9a8db5212c2\node\node.exe",
]

EXPECTED_SCRIPTS = [
    "core.js", "format.js", "verify.js",
    "student.js", "log.js", "chat.js", "main.js",
]

# U12 R1: the issuing console lives on its own page and keeps registrar.js.
STAFF_SCRIPTS = [
    "core.js", "format.js", "verify.js", "registrar.js",
    "student.js", "log.js", "chat.js", "main.js",
]


def find_node() -> str | None:
    for path in NODE_CANDIDATES:
        if path and Path(path).exists():
            return path
    return None


def setUpModule():
    from fastapi.testclient import TestClient

    from tests._bootstrap import isolated_chain_dir

    isolated_chain_dir(prefix="gef26-front-")
    global client
    from app.main import app as _app
    client = TestClient(_app)


def _html() -> str:
    """U25: the detailed console moved to /portal; the landing page is now a
    one-screen verify form, checked separately in SimplePages."""
    return (STATIC / "portal.html").read_text(encoding="utf-8")


class ShellStructure(unittest.TestCase):
    """U6.1: index.html is a shell plus external assets."""

    def test_no_inline_script_body(self):
        inline = [
            body for attrs, body in
            re.findall(r"<script([^>]*)>(.*?)</script>", _html(), re.S)
            if "src=" not in attrs and body.strip()
        ]
        self.assertEqual(inline, [], "index.html still contains an inline <script> body")

    def test_scripts_are_referenced_in_order(self):
        srcs = re.findall(r'<script src="([^"]+)"></script>', _html())
        self.assertEqual(
            [Path(s).name for s in srcs], EXPECTED_SCRIPTS,
            "script tag list or load order changed",
        )
        for src in srcs:
            self.assertTrue(src.startswith("/static/js/"), src)

    def test_stylesheet_linked_and_no_style_block(self):
        html = _html()
        self.assertIn('<link rel="stylesheet" href="/static/css/portal.css">', html)
        self.assertNotIn("<style>", html, "index.html still carries an inline <style> block")

    def test_shell_is_far_smaller_than_legacy(self):
        # U12 R0: the rollback baseline moved out of static/ so it is no longer
        # served over HTTP; it still lives in the repo for rollback.
        legacy = STATIC.parent / "baseline" / "index.legacy.html"
        self.assertTrue(legacy.exists(), "the single-file rollback copy is missing")
        shell_lines = len(_html().splitlines())
        legacy_lines = len(legacy.read_text(encoding="utf-8").splitlines())
        self.assertLess(shell_lines, legacy_lines / 3,
                        f"shell is {shell_lines} lines vs legacy {legacy_lines}")


class AssetsOnDisk(unittest.TestCase):
    def test_every_referenced_asset_exists_and_is_non_trivial(self):
        refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', _html())
        self.assertTrue(refs)
        for ref in refs:
            path = STATIC / ref[len("/static/"):]
            self.assertTrue(path.exists(), f"missing asset {ref}")
            self.assertGreater(path.stat().st_size, 200, f"suspiciously small asset {ref}")

    def test_css_has_the_original_rules(self):
        css = (STATIC / "css" / "portal.css").read_text(encoding="utf-8")
        for token in (".tabs", ".verdict", "@media"):
            self.assertIn(token, css)


class RoleSeparation(unittest.TestCase):
    """U12 R1: the public page must not carry the issuing surface at all."""

    STAFF_PANELS = ("panel-custom", "panel-issue", "panel-revoke", "panel-signers")

    def test_public_page_has_no_staff_panel(self):
        html = _html()
        for panel in self.STAFF_PANELS:
            self.assertNotIn(f'id="{panel}"', html, panel)

    def test_public_page_does_not_load_registrar_js(self):
        self.assertNotIn("registrar.js", _html())

    def test_staff_page_is_separate_and_complete(self):
        staff = (STATIC / "staff.html").read_text(encoding="utf-8")
        self.assertIn('id="panel-issue"', staff)
        srcs = [Path(s).name for s in
                re.findall(r'<script src="([^"]+)"></script>', staff)]
        self.assertEqual(srcs, STAFF_SCRIPTS, "staff page script list changed")

    def test_staff_route_is_absent_without_token(self):
        res = client.get("/staff")
        self.assertEqual(res.status_code, 404,
                         "staff console must not be advertised on a public instance")


class StaffSession(unittest.TestCase):
    """U12 R2: token exchange -> HttpOnly cookie -> console access."""

    TOKEN = "u12-staff-test-token"

    def setUp(self):
        from app import config as cfg
        self._old = (cfg.ADMIN_TOKEN, cfg.PUBLIC_MODE, cfg.ISSUER_TOKEN)
        cfg.ADMIN_TOKEN = self.TOKEN
        cfg.PUBLIC_MODE = False
        client.cookies.clear()

    def tearDown(self):
        from app import config as cfg
        cfg.ADMIN_TOKEN, cfg.PUBLIC_MODE, cfg.ISSUER_TOKEN = self._old
        client.cookies.clear()

    def test_login_page_served_when_token_configured(self):
        res = client.get("/staff/login")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Staff sign-in", res.text)

    def test_staff_redirects_to_login_without_session(self):
        res = client.get("/staff", follow_redirects=False)
        self.assertEqual(res.status_code, 303)
        self.assertEqual(res.headers.get("location"), "/staff/login")

    def test_login_sets_httponly_cookie_and_opens_console(self):
        res = client.post("/staff/login", json={"token": self.TOKEN})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))
        set_cookie = res.headers.get("set-cookie", "").lower()
        self.assertIn("httponly", set_cookie, "session cookie must be HttpOnly")
        self.assertIn("samesite=strict", set_cookie)
        console = client.get("/staff")
        self.assertEqual(console.status_code, 200)
        self.assertIn('id="panel-issue"', console.text)

    def test_bad_token_is_rejected_and_sets_no_cookie(self):
        client.cookies.clear()
        res = client.post("/staff/login", json={"token": "wrong-token"})
        self.assertEqual(res.status_code, 401)
        self.assertNotIn("staff_sid", client.cookies)

    def test_logout_drops_the_session(self):
        client.post("/staff/login", json={"token": self.TOKEN})
        self.assertEqual(client.get("/staff").status_code, 200)
        self.assertEqual(client.post("/staff/logout").status_code, 200)
        res = client.get("/staff", follow_redirects=False)
        self.assertEqual(res.status_code, 303)

    def test_header_token_still_works_for_cli(self):
        client.cookies.clear()
        res = client.get("/staff", headers={"X-Admin-Token": self.TOKEN})
        self.assertEqual(res.status_code, 200)


class StaticMount(unittest.TestCase):
    """Before U6.1 nothing was mounted: the page carried its own CSS and JS."""

    def test_css_served(self):
        res = client.get("/static/css/portal.css")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/css", res.headers.get("content-type", ""))

    def test_each_script_served(self):
        for name in EXPECTED_SCRIPTS:
            res = client.get(f"/static/js/{name}")
            self.assertEqual(res.status_code, 200, name)
            self.assertIn("javascript", res.headers.get("content-type", ""), name)

    def test_page_still_renders(self):
        res = client.get("/portal")
        self.assertEqual(res.status_code, 200)
        self.assertIn("/static/js/main.js", res.text)
        self.assertNotIn("innerHTML", res.text)


class SimplePages(unittest.TestCase):
    """U25: one screen to verify, three fields to issue.

    The landing page stopped being a console. These tests pin the parts a
    future edit is most likely to undo: the header still names the portal,
    the two new pages load their own assets, and neither page builds markup
    from strings (the escaping risk the old page was audited for).
    """

    def test_landing_page_is_the_simple_verify_screen(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("/static/css/simple.css", html)
        self.assertIn("/static/js/simple_verify.js", html)
        self.assertNotIn("<style>", html)
        self.assertNotIn("innerHTML", html)
        for gone in ("panel-verify", "panel-issue", "home-hero", 'class="tabs"'):
            self.assertNotIn(gone, html, f"landing page still carries {gone}")

    def test_simple_verify_js_does_not_build_markup_from_strings(self):
        src = (STATIC / "js" / "simple_verify.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", src)
        self.assertNotIn("insertAdjacentHTML", src)
        self.assertIn("textContent", src)

    def test_issue_page_has_three_required_fields(self):
        html = (STATIC / "issue.html").read_text(encoding="utf-8")
        self.assertIn("/static/js/simple_issue.js", html)
        self.assertEqual(html.count(" required"), 3,
                         "the issuing form must ask for exactly three things")
        self.assertNotIn("panel-issue", html)

    def test_issue_page_is_served(self):
        res = client.get("/issue")
        self.assertEqual(res.status_code, 200)
        self.assertIn("開一張證書", res.text)

    def test_landing_page_still_names_the_portal(self):
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Credential Verification Portal", res.text)
        self.assertNotIn("innerHTML", res.text)

    def test_showtime_page_is_served(self):
        """U26: the stage screen is a page, not a slide."""
        res = client.get("/showtime")
        self.assertEqual(res.status_code, 200)
        self.assertIn("四個環節", res.text)
        self.assertIn("/static/js/showtime.js", res.text)
        self.assertNotIn("innerHTML", res.text)

    def test_showtime_js_runs_the_four_calls(self):
        src = (STATIC / "js" / "showtime.js").read_text(encoding="utf-8")
        for call in ("/api/custom/build", "/api/verify/", "/api/revoke", "/healthz"):
            self.assertIn(call, src)
        self.assertNotIn("innerHTML", src)


class JavaScript(unittest.TestCase):
    def setUp(self):
        self.node = find_node()
        if not self.node:
            self.skipTest("node not found (set NODE_BIN to enable JS tests)")

    def test_js_files_parse(self):
        for name in EXPECTED_SCRIPTS:
            proc = subprocess.run(
                [self.node, "--check", str(STATIC / "js" / name)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr.strip()}")

    def test_escaping_suite(self):
        proc = subprocess.run(
            [self.node, str(FRONTEND / "harness.mjs"), str(STATIC)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("frontend assertions passed", proc.stdout)

    def test_suite_is_not_vacuous(self):
        """Revert one fix in a copy and the harness must go red."""
        proc = subprocess.run(
            [sys.executable, str(FRONTEND / "mutation_check.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("renderBatch must not emit a raw", proc.stdout)


if __name__ == "__main__":
    unittest.main()
