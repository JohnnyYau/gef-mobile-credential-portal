"""Boot the real server and hit it over HTTP (proof of the live entry point)."""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8014"
PY = sys.executable


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return resp.status, resp.read()


server = subprocess.Popen(
    [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8014"],
    cwd=str(ROOT),
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    for _ in range(30):
        try:
            get("/healthz")
            break
        except Exception:
            time.sleep(0.5)
    st, body = get("/healthz")
    print("healthz:", st, json.loads(body)["status"])
    st, body = get("/")
    print("index:", st, "credential verification portal" in body.decode("utf-8", "ignore").lower())
    st, body = get("/api/version")
    v = json.loads(body)
    print("version:", v["version"], "public_mode:", v["public_mode"], "height:", v["chain"]["height"])
    st, body = get("/api/demo/credentials")
    creds = json.loads(body)
    st, body = get("/api/verify/" + creds["diploma"]["hashed_document"])
    d = json.loads(body)
    print("verify sample:", d["verdict"], "receipt:", d["receipt_id"])
    st, body = get("/api/statuslist")
    sl = json.loads(body)
    print("statuslist schema:", sl["schema"], "signature algo:", sl["signature"]["algo"])
finally:
    server.terminate()
    server.wait(timeout=10)
print("LIVE CHECK OK")
