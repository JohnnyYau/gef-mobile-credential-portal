# -*- coding: utf-8 -*-
"""U12 R0 smoke: the static whitelist actually closes what it claims to close."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CHECKS = [
    ("/static/css/portal.css", 200),
    ("/static/js/main.js", 200),
    ("/static/js/core.js", 200),
    ("/static/index.html", 404),
    ("/static/index.legacy.html", 404),
    ("/static/staff.html", 404),
    ("/static/../app/config.py", 404),
    ("/staff", 404),
    ("/api/student/22000000?dob=19880808", 404),
    ("/me/forged.token", 404),
    ("/", 200),
]

failures = []
for path, expected in CHECKS:
    res = client.get(path)
    got = res.status_code
    ok = got == expected
    print(f"{'OK  ' if ok else 'FAIL'} {path:<28} expected {expected} got {got}")
    if not ok:
        failures.append(path)

if failures:
    raise SystemExit(f"R0 smoke failed: {failures}")
print("R0 smoke passed")
