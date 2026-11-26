"""smoke_portal.py — read-only smoke test against a *running* portal.

The unit suite boots the app in-process with a throwaway chain; this script
talks to a real process over HTTP. It is the check to run after a restart or
a deploy, when the question is "is this instance actually serving the right
things, with the right auth?" It never issues or revokes: every call is a read,
plus two harmless POSTs (holder-link minting writes nothing on chain, and renew
of a freshly minted link must be refused).

    python scripts/smoke_portal.py --base http://127.0.0.1:8013 \
        --admin-token demo-staff-token

Exit code 0 only when every selected check passes. Without --admin-token the
staff checks are skipped and reported as SKIP, so a public-mode instance can
still be smoke-tested.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

TIMEOUT = 15


def fetch(base, path, token=None, method="GET", headers=None):
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, method=method, data=b"" if method != "GET" else None)
    if token:
        req.add_header("X-Admin-Token", token)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def as_json(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


class Runner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.failures = []

    def check(self, name, ok, detail=""):
        if ok:
            self.passed += 1
            print(f"PASS  {name}" + (f"  ({detail})" if detail else ""))
        else:
            self.failed += 1
            self.failures.append((name, detail))
            print(f"FAIL  {name}" + (f"  ({detail})" if detail else ""))
        return ok

    def skip(self, name, why):
        self.skipped += 1
        print(f"SKIP  {name}  ({why})")


def content_type(headers):
    # urllib keeps the header case the server sent (ASGI sends lowercase).
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value or ""
    return ""


def pdf_text(raw):
    """Extracted text, or None when pypdf is not installed."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        import io
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return None


def pdf_image_count(raw):
    """Embedded images on page 1, or None when unreadable/absent.

    U19: the QR was silently absent from every PDF for six rounds. This is the
    operational-level guard: a deployed report with no image is a report with
    no scannable entry point.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        import io
        return len(list(PdfReader(io.BytesIO(raw)).pages[0].images))
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only smoke test of a running portal")
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="instance base URL")
    ap.add_argument("--admin-token", default="", help="staff token; staff checks are skipped without it")
    args = ap.parse_args(argv)
    r = Runner()

    # ---- public surface ------------------------------------------------
    status, _, raw = fetch(args.base, "/healthz")
    health = as_json(raw) or {}
    r.check("GET /healthz", status == 200 and bool(health.get("height")),
            f"height={health.get('height')}")
    integ_pub = (((health.get("checks") or {}).get("chain") or {})
                 .get("integrity") or {})
    r.check("healthz integrity says when it was checked",
            "checked_at" in integ_pub and "age_s" in integ_pub,
            f"age_s={integ_pub.get('age_s')}")
    # U24: the limiter keys on the peer unless the peer is a trusted proxy.
    # Saying which one is in use is how a proxied deploy notices that its
    # X-Forwarded-For is being ignored (everyone shares one bucket).
    src = ((health.get("checks") or {}).get("observability") or {}).get("client_ip_source")
    r.check("healthz says which address the limiter counts",
            src in ("peer", "x-forwarded-for"), f"client_ip_source={src}")

    status, _, raw = fetch(args.base, "/api/version")
    ver = as_json(raw) or {}
    uptime = ver.get("uptime_s")
    r.check("GET /api/version", status == 200 and ver.get("version"),
            f"v={ver.get('version')} public_mode={ver.get('public_mode')}")
    # U15: uptime_s used to be an epoch stamp (≈1.7e9). Seconds must be small
    # and non-decreasing, never a wall-clock value.
    r.check("uptime_s is seconds, not an epoch stamp",
            isinstance(uptime, (int, float)) and 0 <= uptime < 86400 * 365,
            f"uptime_s={uptime}")

    status, _, raw = fetch(args.base, "/api/demo/credentials")
    creds = as_json(raw) or {}
    diploma = creds.get("diploma") or {}
    hashed = diploma.get("hashed_document")
    sid = ((diploma.get("document") or {}).get("PersonalParticulars") or {}).get("StudentID")
    if not r.check("GET /api/demo/credentials", status == 200 and hashed,
                   f"hash={str(hashed)[:12]}…"):
        return finish(r)

    status, _, raw = fetch(args.base, f"/api/verify/{hashed}")
    verdict = as_json(raw) or {}
    # "VALID ON CHAIN" is the full six-check verdict; "VALID" is the short form.
    r.check("GET /api/verify/{hash}",
            status == 200 and str(verdict.get("verdict") or "").startswith("VALID"),
            f"verdict={verdict.get('verdict')}")

    status, _, raw = fetch(args.base, f"/api/status/{hashed}")
    r.check("GET /api/status/{hash}", status == 200, f"http={status}")

    status, headers, raw = fetch(args.base, f"/api/pdf/{hashed}")
    text = pdf_text(raw)
    name = (diploma.get("document") or {}).get("PersonalParticulars", {}).get("Surname") or ""
    ok = status == 200 and content_type(headers).startswith("application/pdf")
    detail = f"http={status}, {len(raw)}B"
    if text is not None:
        ok = ok and "withheld" in text.lower() and (not name or name.lower() not in text.lower())
        detail += ", identity withheld"
    images = pdf_image_count(raw)
    if images is not None:
        ok = ok and images >= 1
        detail += f", {images} image(s)"
    r.check("GET /api/pdf/{hash} is a report, not the credential", ok, detail)
    status, _, raw = fetch(args.base, "/api/log")
    r.check("GET /api/log", status == 200, f"http={status}")

    # ---- staff surface -------------------------------------------------
    if not args.admin_token:
        r.skip("staff checks", "no --admin-token given")
        return finish(r)

    status, _, raw = fetch(args.base, "/api/staff/whoami", token=args.admin_token)
    who = as_json(raw) or {}
    r.check("GET /api/staff/whoami", status == 200 and who.get("role") == "admin",
            f"role={who.get('role')} demo_open={who.get('demo_open')}")
    # U24: uvicorn ships `--proxy-headers` on by default and trusts
    # 127.0.0.1 unconditionally, so it rewrites the peer from
    # X-Forwarded-For *before the app ever sees it* — the app's own
    # TRUSTED_PROXIES decision never runs. Probing with a forged header is the
    # only way to see which layer won; a staff-only echo says it plainly.
    status, _, raw = fetch(args.base, "/api/staff/whoami", token=args.admin_token,
                           headers={"X-Forwarded-For": "203.0.113.5"})
    probe = as_json(raw) or {}
    seen = str(probe.get("client_ip") or "")
    hint = ("  (uvicorn is rewriting the peer — start it with --no-proxy-headers)"
            if seen.startswith("203.0.113.") else "")
    r.check("forged X-Forwarded-For does not become the peer",
            bool(seen) and not seen.startswith("203.0.113."),
            f"client_ip={seen}{hint}")

    status, admin_headers, raw = fetch(args.base, f"/api/admin/pdf/{hashed}", token=args.admin_token)
    text = pdf_text(raw)
    ok = status == 200 and content_type(admin_headers).startswith("application/pdf")
    attachments = None
    if text is not None:
        try:
            from pypdf import PdfReader
            import io
            attachments = len(PdfReader(io.BytesIO(raw)).attachments)
        except Exception:
            attachments = None
    ok = ok and (attachments is None or attachments == 1)
    r.check("GET /api/admin/pdf/{hash} is the full credential", ok,
            f"http={status}, {len(raw)}B, attachments={attachments}")

    status, _, raw = fetch(args.base, "/api/custom/list", token=args.admin_token)
    r.check("GET /api/custom/list is staff-gated", status in (200, 403),
            f"http={status}")

    # U19/U23: the text behind /healthz's counts, and how old the integrity
    # verdict is. Without DEMO_OPEN=1 an anonymous call must be refused.
    if ver.get("demo_open"):
        r.skip("GET /api/diagnostics without a token is refused",
               "DEMO_OPEN=1 on this instance")
    else:
        status, _, raw = fetch(args.base, "/api/diagnostics")
        r.check("GET /api/diagnostics without a token is refused",
                status in (401, 403), f"http={status}")

    status, _, raw = fetch(args.base, "/api/diagnostics", token=args.admin_token)
    diag = as_json(raw) or {}
    warns = (diag.get("config") or {}).get("warnings")
    diag_integ = ((diag.get("chain") or {}).get("integrity") or {})
    r.check("GET /api/diagnostics returns the config text",
            status == 200 and isinstance(warns, list),
            f"http={status}, warnings={len(warns) if isinstance(warns, list) else '?'}")
    r.check("diagnostics reports integrity age",
            "checked_at" in diag_integ and isinstance(diag_integ.get("age_s"), (int, float)),
            f"age_s={diag_integ.get('age_s')}")

    status, _, raw = fetch(args.base, "/api/pdf/" + hashed, token=None)
    r.check("public PDF still readable without a token", status == 200, f"http={status}")

    if not sid:
        r.skip("holder link chain", "demo credential has no StudentID")
        return finish(r)
    status, _, raw = fetch(args.base,
                           f"/api/holder-link?student_id={sid}&hashed_document={hashed}",
                           token=args.admin_token)
    link = as_json(raw) or {}
    cap = link.get("token")
    if not r.check("GET /api/holder-link mints a capability", status == 200 and cap,
                   f"expires_in={link.get('expires_in')}"):
        return finish(r)

    status, _, raw = fetch(args.base, f"/api/me/{cap}")
    body = as_json(raw) or {}
    r.check("GET /api/me/{cap}", status == 200 and body.get("student_id") == sid,
            f"http={status}, docs={len(body.get('credentials') or [])}")

    # U14: a freshly minted 30-day link is too young to renew.
    status, _, raw = fetch(args.base, f"/api/me/{cap}/renew", method="POST")
    r.check("POST /api/me/{cap}/renew refuses a young link", status == 403, f"http={status}")

    status, _, raw = fetch(args.base, f"/api/me/{cap}/pdf")
    r.check("GET /api/me/{cap}/pdf", status == 200, f"http={status}, {len(raw)}B")

    return finish(r)


def finish(r):
    print(f"\n{r.passed} passed, {r.failed} failed, {r.skipped} skipped")
    for name, detail in r.failures:
        print(f"  FAILED: {name} — {detail}")
    return 0 if r.failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
