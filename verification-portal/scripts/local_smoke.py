"""Local smoke for the upgraded portal (no external deps beyond runtime).

Usage:
    python scripts/local_smoke.py public   # public verifier checks (default)
    python scripts/local_smoke.py private  # admin issue/revoke + API-key checks

Each phase runs in a fresh process so PUBLIC_MODE is evaluated at import time.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PHASE = sys.argv[1] if len(sys.argv) > 1 else "public"
os.environ["CHAIN_DIR"] = tempfile.mkdtemp(prefix="gef26-smoke-")
os.environ["PUBLIC_MODE"] = "0" if PHASE == "private" else "1"

from fastapi.testclient import TestClient  # noqa: E402
from app import chain_service  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" " + str(extra) if extra else ""))
    if not cond:
        fails.append(name)


if PHASE == "public":
    # 1. health + version (public mode)
    r = client.get("/healthz")
    check("healthz 200 ok", r.status_code == 200 and r.json().get("status") == "ok")
    r = client.get("/api/version")
    v = r.json()
    check("version public_mode", r.status_code == 200 and v.get("public_mode") is True)
    check("version app/version", v.get("app") == "Gef26 credential verification portal"
          and v.get("version") == "6.0.0")
    check("version chain seeded", (v.get("chain") or {}).get("height", 0) >= 2)
    check("version statuslist digest", bool(v.get("statuslist_digest")))

    # 2. admin blocked in public mode
    r = client.post("/api/issue", json={"document": chain_service.SAMPLE_DIPLOMA})
    check("issue 403 in public mode", r.status_code == 403)

    # 3. samples
    r = client.get("/api/demo/credentials")
    creds = r.json()
    check("demo creds dict", isinstance(creds, dict))
    valid_h = creds["diploma"]["hashed_document"]
    check("revoked_sample present", "revoked_sample" in creds)

    # 4. verify valid
    r = client.get(f"/api/verify/{valid_h}")
    d = r.json()
    check("verify valid -> VALID ON CHAIN", d.get("verdict") == "VALID ON CHAIN")
    check("verify receipt id", str(d.get("receipt_id", "")).startswith("RCP-"))

    # 5. verify revoked sample
    rs = creds["revoked_sample"]["hashed_document"]
    r = client.get(f"/api/verify/{rs}")
    check("verify revoked -> REVOKED", r.json().get("verdict") == "REVOKED")

    # 6-7. not found + malformed
    check("verify not found", client.get("/api/verify/" + "Z" * 44).json().get("verdict") == "NOT FOUND")
    check("verify malformed 422", client.get("/api/verify/abc").status_code == 422)

    # 8. batch
    r = client.post("/api/verify/batch", json={"hashes": [valid_h, "Z" * 44, ""]})
    b = r.json()
    check("batch summary", b["summary"]["total"] == 3 and b["summary"]["valid"] == 1
          and b["summary"]["not_found"] == 1 and b["summary"]["error"] == 1)
    check("batch receipt on row", str(b["results"][0].get("receipt_id", "")).startswith("RCP-"))

    # 9. statuslist signed + etag
    r = client.get("/api/statuslist")
    sl = r.json()
    check("statuslist schema", sl.get("schema") == "gef26.statuslist.v1")
    check("statuslist signature", bool(sl.get("signature", {}).get("value")))
    etag = r.headers.get("etag")
    check("statuslist etag", bool(etag))
    check("statuslist 304", client.get("/api/statuslist",
                                       headers={"If-None-Match": etag}).status_code == 304)

    # 10. receipt roundtrip
    rid = client.get(f"/api/verify/{valid_h}").json()["receipt_id"]
    r = client.get(f"/api/receipt/{rid}")
    check("receipt lookup", r.status_code == 200 and r.json()["receipt_id"] == rid)
    check("receipt malformed 422", client.get("/api/receipt/NOPE").status_code == 422)

    # 11. no admin in public mode
    check("apikeys 403 in public", client.get("/api/admin/apikeys").status_code == 403)

    # 12-13. chat + student
    r = client.post("/api/chat", json={"question": "Has CHAN TAI MAN's diploma been revoked?"})
    check("chat answers", r.status_code == 200 and bool(r.json().get("answer")))
    check("rag status", client.get("/api/rag/status").status_code == 200)
    check("student requires dob 404", client.get("/api/student/22000000").status_code == 404)
    r = client.get("/api/student/22000000?dob=19880808")
    check("student lookup", r.status_code == 200 and len(r.json()["credentials"]) >= 1)

else:  # private
    valid_h = chain_service.demo_credentials()["diploma"]["hashed_document"]

    r = client.post("/api/issue", json={"document": chain_service.SAMPLE_DIPLOMA})
    check("private issue 200", r.status_code == 200)
    h = r.json()["hashed_document"]

    r = client.post("/api/revoke", json={"hashed_document": h, "reason": "admin error",
                                         "effective_at": 1700000000})
    check("revoke 200", r.status_code == 200)
    d = client.get(f"/api/verify/{h}").json()
    check("verify revoked + reason", d.get("verdict") == "REVOKED"
          and d.get("reason") == "admin error" and d.get("effective_at") == 1700000000)

    r = client.post("/api/admin/apikeys", json={"name": "smoke key"})
    check("create apikey", r.status_code == 200 and bool(r.json().get("key")))
    key, kid = r.json()["key"], r.json()["id"]
    check("apikey auth works", client.get("/api/verify/" + valid_h,
                                          headers={"Authorization": "Bearer " + key}).status_code == 200)
    check("bad apikey 401", client.get("/api/verify/" + valid_h,
                                       headers={"Authorization": "Bearer nope"}).status_code == 401)
    check("revoke apikey", client.delete(f"/api/admin/apikeys/{kid}").status_code == 200)
    check("revoked apikey 401", client.get("/api/verify/" + valid_h,
                                           headers={"Authorization": "Bearer " + key}).status_code == 401)

print()
print("SMOKE FAILURES: " + (", ".join(fails) if fails else "none"))
sys.exit(1 if fails else 0)
