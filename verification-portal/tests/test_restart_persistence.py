"""Extras round 7 — restart persistence + snapshot restore.

Two integration tests against the real server (uvicorn subprocess):

1. issue via the API, kill the server, start it again, and the credential
   must still verify (chain + raw docs survive on disk);
2. with an empty chain dir and CHAIN_SNAPSHOT_URL set, the app restores from
   the snapshot at boot (free-tier ephemeral storage scenario).

These take a few seconds each; they are deliberately last in the suite.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"
ROOT = Path(__file__).resolve().parent.parent


def _wait_ready(base: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # noqa: BLE001 — server not up yet
            time.sleep(0.4)
    return False


def _spawn(env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, env={**os.environ, **env},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _issue_via_api() -> str:
    doc = {
        "PersonalParticulars": {"Surname": "RESTART", "GivenNames": "PROOF",
                                "Sex": "M", "DOB": "19991231", "StudentID": "77770000"},
        "AcademicInfo": {"DegreeName": "BSc Persistence", "DegreeStartDate": "20200101",
                         "DegreeEndDate": "20240101", "Honour": "1ST", "Observations": ""},
        "DocumentInfo": {"DateOfIssue": "20240115", "AuthorizedSignature": "REG",
                         "IssuingO": "UNIVERSITY OF UTOPIA", "IssuingOU": "RECORD OFFICE",
                         "DocType": "DIPLOMA"},
    }
    req = urllib.request.Request(
        BASE + "/api/issue",
        data=json.dumps({"document": doc}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["hashed_document"]


@unittest.skipUnless(shutil.which("uvicorn") or True, "uvicorn required")
class RestartPersistenceTest(unittest.TestCase):

    def test_issue_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            chain_dir = Path(tmp) / "chain"
            env = {"CHAIN_DIR": str(chain_dir), "PUBLIC_MODE": "0"}
            server = _spawn(env)
            try:
                self.assertTrue(_wait_ready(BASE), "server did not become ready")
                h = _issue_via_api()
            finally:
                server.terminate()
                server.wait(timeout=10)

            # restart against the same CHAIN_DIR
            server = _spawn(env)
            try:
                self.assertTrue(_wait_ready(BASE), "server did not restart")
                with urllib.request.urlopen(BASE + "/api/verify/" + h, timeout=10) as resp:
                    verdict = json.loads(resp.read())["verdict"]
                self.assertIn("VALID", verdict)
            finally:
                server.terminate()
                server.wait(timeout=10)

    def test_snapshot_restore_on_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            src_chain = root_dir / "src-chain"
            dst_chain = root_dir / "dst-chain"

            # seed a real chain, then export it
            env = {"CHAIN_DIR": str(src_chain), "PUBLIC_MODE": "0"}
            server = _spawn(env)
            try:
                self.assertTrue(_wait_ready(BASE))
            finally:
                server.terminate()
                server.wait(timeout=10)

            import scripts.backup_chain as backup
            snapshot = root_dir / "chain-backup.tar.gz"
            backup.export_chain(src_chain, snapshot, exclude_keys=False)

            # boot against an empty chain dir with the snapshot URL set
            import http.server
            import threading
            handler = http.server.SimpleHTTPRequestHandler
            os.chdir(str(root_dir))
            try:
                httpd = http.server.HTTPServer(("127.0.0.1", 8124), handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                try:
                    env = {"CHAIN_DIR": str(dst_chain),
                           "CHAIN_SNAPSHOT_URL": "http://127.0.0.1:8124/chain-backup.tar.gz",
                           "PUBLIC_MODE": "0"}
                    server = _spawn(env)
                    try:
                        self.assertTrue(_wait_ready(BASE))
                        with urllib.request.urlopen(BASE + "/healthz", timeout=10) as resp:
                            info = json.loads(resp.read())
                        self.assertEqual(info["height"], src_height(src_chain))
                    finally:
                        server.terminate()
                        server.wait(timeout=10)
                finally:
                    httpd.shutdown()
            finally:
                os.chdir(str(ROOT))  # leave the tempdir before cleanup (Windows)


def src_height(chain_dir: Path) -> int:
    """Re-read the source chain's last height from its blocks."""
    import glob
    paths = glob.glob(str(chain_dir / "blocks" / "block-*.json"))
    heights = [int(p.split("block-")[1].split(".json")[0]) for p in paths]
    return max(heights) if heights else 0


if __name__ == "__main__":
    unittest.main()
