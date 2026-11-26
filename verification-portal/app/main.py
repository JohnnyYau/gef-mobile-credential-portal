"""main.py — FastAPI application for the credential verification portal.

Weeks 1-3 scope (per the 3-week plan):
    POST /api/issue            issue a credential document (admin)
    POST /api/revoke           revoke by hash or document (admin)
    GET  /api/verify/{hash}    hash-level verdict with the six checks
    GET  /api/status/{hash}    raw lifecycle (issued/revoked + heights)
    POST /api/verify/document  upload a credential -> full six-check verdict
    POST /api/chat             RAG question -> answer + cited sources (Week 2)

Week 3 hardening: rate limiting, request-size / JSON-depth guards, graceful
handling of corrupted chain data. Admin endpoints are open by default for the
demo; set ADMIN_TOKEN to require `X-Admin-Token: <token>`.

Post-Week-3 extras: QR codes, a public (anonymized) log, a signer-velocity
anomaly watch, verifiable diploma PDFs, student self-service lookup,
multi-signer management and email notifications.

Extras round 5: public verifier mode (PUBLIC_MODE=1) — verification surface
only; every admin endpoint returns 403 and the UI hides the admin tabs.
Extras round 6 (employer pack): batch verify, public API keys, signed
revocation status list, receipt registry, revocation reason/effective date.
Extras round 7: free-tier persistence (CHAIN_SNAPSHOT_URL restore on boot).
"""

import ipaddress
import json
import os
import re
import time
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError as PydanticValidationError

from . import (
    anomaly,
    apikeys,
    audit,
    authz,
    blockchain_util,
    capability,
    chain_service,
    chat_service,
    custom_service,
    disclosure,
    notifier,
    pdf_diploma,
    pdf_extractor,
    receipt_registry,
    repository,
    startup,
    statuslist,
)
from . import config as cfg
from . import (
    observability as obs,
)
from .config import (
    CHAIN_DIR,
    MAX_BODY_BYTES,
    MAX_JSON_BYTES,
    MAX_JSON_DEPTH,
    MAX_UPLOAD_BYTES,
    PUBLIC_BASE_URL,
    RATE_LIMIT_ADMIN_MAX,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_PUBLIC_MAX,
    STATIC_DIR,
)
from .public_log import verification_log
from .rate_limit import SlidingWindowLimiter
from .schemas import (
    ActiveSignerBody,
    AddSignerBody,
    ApiKeyCreateBody,
    ChatBody,
    CustomBuildBody,
    DiscloseBody,
    IssueBatchBody,
    IssueBody,
    RetireSignerBody,
    RevokeBody,
    VerifyBatchBody,
    VerifyDocumentBody,
)

HASH_RE = re.compile(r"^[A-Za-z0-9_-]{16,200}$")
SIX_CHECKS = ("chain_integrity", "signer_trusted", "on_chain_record",
              "hash_match", "signature_valid", "not_revoked")

_public_limiter = SlidingWindowLimiter()
_admin_limiter = SlidingWindowLimiter()
_EXEMPT_PATHS = {"/", "/healthz", "/api/version"}
_started_at = time.time()


CONFIG_REPORT: dict[str, list[str]] = {"fatal": [], "warnings": []}


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Validate configuration, seed/restore the chain, release on shutdown.

    U8.2: configuration is checked *before* anything else touches storage, so
    a `STORAGE_BACKEND=sqlitee` typo or an unwritable CHAIN_DIR fails here with
    one clear message instead of surfacing mid-issuance as "VALID" on data
    that was never written. Warnings are logged, not fatal: a missing mail
    server must not stop a demo, but an unimplemented backend must.
    """
    report = startup.validate_config(cfg)
    CONFIG_REPORT.clear()
    CONFIG_REPORT.update(report)
    for warning in report["warnings"]:
        obs.log_event("warning", "config", detail=warning)
    if report["fatal"]:
        raise RuntimeError("configuration is not usable: "
                           + "; ".join(report["fatal"]))
    try:
        if cfg.CHAIN_SNAPSHOT_URL:
            chain_service.restore_snapshot_if_needed(cfg.CHAIN_SNAPSHOT_URL)
        chain_service.ensure_chain()
        notifier.start_worker()   # U12 R4: sending happens off the request path
        obs.log_event("info", "startup", backend=cfg.STORAGE_BACKEND,
                      warnings=len(report["warnings"]))
    except BaseException:
        repository.close_all()      # do not leave stores cached on a failed boot
        raise
    try:
        yield
    finally:
        # U12 R4: the worker is the app's only background thread. Stop it and
        # flush what it has queued before the stores close underneath it.
        notifier.stop_worker()
        closed = repository.close_all()
        obs.log_event("info", "shutdown", bundles_closed=closed)


app = FastAPI(title="Credential Verification Portal", version="1.0.0",
              lifespan=_lifespan)


_ID_SEGMENT_RE = re.compile(r"(?<=/)[A-Za-z0-9_-]{16,}")


def _endpoint_label(path: str) -> str:
    """Bucket path parameters before they reach metrics or logs.

    A raw path is a high-cardinality key *and* a leak: ``/api/verify/<hash>``
    would put a credential hash into every metric bucket. Segments of 16+
    base64url characters are collapsed to ``{id}``.
    """
    return _ID_SEGMENT_RE.sub("{id}", path)


@app.middleware("http")
async def _hardening_middleware(request: Request, call_next):
    """Correlation id + body cap + per-IP rate limiting + origin check.

    Requests with a valid ``Authorization: Bearer <api-key>`` get a per-key
    bucket at API_KEY_MAX (the "public verification API"); anonymous web
    traffic stays on the shared per-IP bucket.

    Every exit path — including the three rejections below — carries
    ``X-Request-ID`` and emits exactly one structured log line plus one metric
    sample, so a 429 is visible in logs instead of vanishing before routing.
    """
    rid = obs.accept_request_id(request.headers.get(obs.REQUEST_ID_HEADER))
    obs.bind_request_id(rid)
    started = time.perf_counter()
    endpoint = _endpoint_label(request.url.path)

    # U9-B: resolve who is calling, for the audit trail. One digest compare for
    # a Bearer key and one string compare for a role token, so this is cheap
    # enough to do on every request regardless of the rate limiter.
    auth = request.headers.get("authorization", "")
    api_key = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    keyed = apikeys.validate_key(api_key) if api_key else None
    if keyed:
        actor = f"apikey:{keyed['id']}"
    else:
        role = authz.resolve_role(request.headers.get(authz.ROLE_HEADER),
                                  (authz.ADMIN, authz.ISSUER))
        actor = f"role:{role}" if role else audit.ANONYMOUS

    def _finish(response: Response, denied: str | None = None) -> Response:
        duration = int((time.perf_counter() - started) * 1000)
        # Static assets keep the browser honest during edits: revalidate every
        # time instead of serving a stale main.js from heuristic cache.
        if request.url.path.startswith("/static/"):
            response.headers["cache-control"] = "no-cache"
        obs.COUNTERS.record_request(endpoint, response.status_code, duration)
        if denied:
            obs.COUNTERS.record_denial(denied)
        obs.log_event(
            "warning" if response.status_code >= 400 else "info",
            "request",
            endpoint=endpoint,
            method=request.method,
            status=response.status_code,
            duration_ms=duration,
            denied=denied,
        )
        response.headers[obs.REQUEST_ID_HEADER] = rid
        return response

    origin = request.headers.get("origin")
    if (origin and request.method not in ("GET", "HEAD", "OPTIONS")
            and not _origin_allowed(origin, request.headers.get("host"))):
        return _finish(JSONResponse(
            status_code=403,
            content={"detail": "Cross-origin request rejected."}), "origin")

    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return _finish(JSONResponse(status_code=413,
                                    content={"detail": "Request body too large."}),
                       "body_too_large")

    if RATE_LIMIT_ENABLED and request.url.path not in _EXEMPT_PATHS:
        if api_key and keyed is None:
            return _finish(JSONResponse(
                status_code=401,
                content={"detail": "Invalid or revoked API key."}))
        key = "apikey:" + keyed["id"] if keyed else _client_ip(request)
        admin = request.url.path.startswith(("/api/issue", "/api/revoke"))
        limiter = _admin_limiter if admin else _public_limiter
        limit = (RATE_LIMIT_ADMIN_MAX if admin
                 else (cfg.API_KEY_MAX if keyed else RATE_LIMIT_PUBLIC_MAX))
        if not limiter.allow(key, limit):
            return _finish(JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded — try again shortly."}),
                "rate_limit")
    audit.set_actor(actor)
    try:
        return _finish(await call_next(request))
    finally:
        audit.clear_actor()


def _origin_allowed(origin: str, host: str | None = None) -> bool:
    """True when ``origin`` may drive a state-changing request.

    Same host as the request being classified is allowed, so the portal's own
    pages work without configuration. Anything else must be listed in
    ``ALLOWED_ORIGINS``. Requests without an ``Origin`` header (curl, tests,
    server-to-server) are not blocked — the browser is the only client that
    sets it, so its absence is not an attack signal.

    U26: the same-host branch used to compare against the literal strings
    127.0.0.1/localhost only. That works on a laptop and fails the moment the
    portal is reached through a tunnel or a real domain: the page is served
    from the public host, its own POST carries that Origin, and the request
    was rejected as cross-origin — issuing was impossible on a public URL
    even with the right token. ``host`` is the request's own Host header; the
    comparison is host-name only, because TLS may terminate at the proxy.
    """
    extra = {o.strip().rstrip("/").lower()
             for o in str(cfg.ALLOWED_ORIGINS or "").split(",") if o.strip()}
    if origin.rstrip("/").lower() in extra:
        return True
    parts = urlsplit(origin)
    if parts.hostname in ("127.0.0.1", "localhost"):
        return True
    if host and parts.hostname:
        request_host = urlsplit("//" + host).hostname or ""
        return parts.hostname.lower() == request_host.lower()
    return False


def _admin_required(request: Request,
                    x_admin_token: str | None = Header(default=None,
                                                       alias=authz.ROLE_HEADER)):
    """Admin-only dependency — behaviour unchanged since before U3.

    Delegates to ``authz.check_roles`` so the token rules (and, since U12 R2,
    the staff session cookie) live in one place; error codes/messages stay
    byte-identical.
    """
    return authz.check_roles((authz.ADMIN,), request, x_admin_token)


def _require_pdf_magic(raw: bytes) -> None:
    """Reject anything that is not a PDF, by content rather than by name.

    The header may legally sit within the first 1024 bytes (some producers put
    a BOM or comment ahead of it), so that is the window searched. ``lstrip()``
    is deliberately NOT used: it would accept a file with an arbitrary binary
    prefix before the marker.
    """
    if b"%PDF" not in raw[:1024]:
        raise HTTPException(
            status_code=422,
            detail="僅支援 PDF 檔案。請上傳證書 PDF（.pdf）。")


def _ttl_days(value) -> int | None:
    """Coerce an optional TTL to a positive int; None/invalid means "never expires"."""
    if value in (None, "", 0, "0"):
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


def _validate_hash(hashed_document: str) -> None:
    if not HASH_RE.match(hashed_document or ""):
        raise HTTPException(
            status_code=422,
            detail="Hash must be a base64url string (16-200 chars, no '=' padding).",
        )


def _json_depth(value, _depth=0):
    if isinstance(value, dict):
        if not value:
            return _depth + 1
        return max(_json_depth(v, _depth + 1) for v in value.values())
    if isinstance(value, list):
        if not value:
            return _depth + 1
        return max(_json_depth(v, _depth + 1) for v in value)
    return _depth


def _validate_document_shape(document: dict) -> None:
    """Reject pathologically large or deeply nested documents (zip-bomb-like)."""
    depth = _json_depth(document)
    if depth > MAX_JSON_DEPTH:
        raise ValueError(f"JSON nesting too deep ({depth} > {MAX_JSON_DEPTH}).")
    size = len(json.dumps(document, ensure_ascii=False))
    if size > MAX_JSON_BYTES:
        raise ValueError(f"Document JSON is too large ({size} bytes > {MAX_JSON_BYTES}).")


# --------------------------------------------------------------------------
# Pages + health + version
# --------------------------------------------------------------------------


@app.get("/")
def index():
    """U25: the landing page is one screen — paste a hash or upload a file,
    read one sentence. The previous multi-tab console moved to /portal."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/portal")
def portal_full():
    """U25: the full console (six checks, batch, log, chat) kept at /portal."""
    return FileResponse(STATIC_DIR / "portal.html")


@app.get("/issue")
def issue_page():
    """U25: three-field issuing page for the institution side.

    The page itself is public like /staff/login; the action behind it
    (POST /api/custom/build) stays admin-guarded, and the page only reveals
    the token box when no staff session is present.
    """
    return FileResponse(STATIC_DIR / "issue.html")


@app.get("/showtime")
def showtime_page():
    """U26: the stage screen — issue, verify, revoke, verify again.

    Every step is a real API call, so a showcase audience watches one
    credential change state instead of watching a slide. Same guard as
    /issue: the writes go through the admin-protected endpoints.
    """
    return FileResponse(STATIC_DIR / "showtime.html")


@app.get("/staff")
def staff_index(request: Request,
                x_admin_token: str | None = Header(default=None,
                                                   alias=authz.ROLE_HEADER)):
    """U12 R1/R2: the staff console, separate from the public page.

    Deliberately returns 404 rather than 403 when the deployment has no staff
    token: on a public instance the route should not appear to exist at all.
    When a token *is* configured but the caller has no session and no header,
    it redirects to the login page instead of leaking a credential prompt.
    """
    if cfg.PUBLIC_MODE or not authz.configured_roles((authz.ADMIN, authz.ISSUER)):
        raise HTTPException(status_code=404, detail="Not Found")
    role = authz.resolve_role(x_admin_token, (authz.ADMIN, authz.ISSUER))
    if role is None:
        role = authz.read_staff_session(request.cookies.get(authz.STAFF_COOKIE))
    if role is None:
        return RedirectResponse("/staff/login", status_code=303)
    return FileResponse(STATIC_DIR / "staff.html")


@app.get("/staff/login")
def staff_login_page():
    if cfg.PUBLIC_MODE or not authz.configured_roles((authz.ADMIN, authz.ISSUER)):
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(STATIC_DIR / "staff_login.html")


_PROXY_CACHE: dict[str, Any] = {"raw": None, "nets": [], "bad": []}


def _proxy_nets() -> tuple[list[Any], list[str]]:
    """Parse `TRUSTED_PROXIES` once per distinct value; returns (nets, bad).

    Entries that do not parse are kept in `bad` so `startup.py` can name them
    in a warning — a typo in this list must not silently turn into "trust
    nobody" (or worse, "trust everybody").
    """
    raw = str(getattr(cfg, "TRUSTED_PROXIES", "") or "").strip()
    if _PROXY_CACHE["raw"] != raw:
        nets: list[Any] = []
        bad: list[str] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                bad.append(part)
        _PROXY_CACHE.update(raw=raw, nets=nets, bad=bad)
    return _PROXY_CACHE["nets"], _PROXY_CACHE["bad"]


def _is_trusted_proxy(addr: str, nets: list[Any]) -> bool:
    """True only for a syntactically valid address inside the trusted list."""
    if not nets or not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False  # "testclient", "unknown", or a malformed hop
    return any(ip in net for net in nets)


def _client_ip(request: Request) -> str:
    """Caller address used as the rate-limit bucket key.

    U16: the login throttle used ``request.client.host`` while the global
    limiter already read ``X-Forwarded-For``. Behind one reverse proxy that
    made every browser share the proxy's address (one lockout for everybody)
    and left the header free to pick a fresh bucket. Both keys now come from
    here.

    U24: but that fix believed the header *unconditionally*, which handed the
    bypass back to the caller: on an instance with no proxy in front, anyone
    could send ``X-Forwarded-For: <random>`` per request and never hit the
    limiter, or pin someone else's bucket shut. The header is now only read
    when the direct peer is listed in ``TRUSTED_PROXIES``; then the address
    returned is the *nearest* hop that is not itself a trusted proxy, looking
    from the right (a client may put anything it likes on the left).
    """
    peer = request.client.host if request.client else "unknown"
    nets, _bad = _proxy_nets()
    if not _is_trusted_proxy(peer, nets):
        return peer  # no proxy in front (or a peer that is not one): ignore XFF
    hops = [h.strip() for h in
            request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if not hops:
        return peer
    for hop in reversed(hops):
        if not _is_trusted_proxy(hop, nets):
            return hop
    return hops[0]  # every hop is a trusted proxy: the leftmost is the client


@app.post("/staff/login")
def staff_login(request: Request, response: Response,
                payload: dict = Body(default=None)):
    """Exchange a staff token for an HttpOnly session cookie.

    The token never lands in localStorage or a JS variable: it is posted once,
    compared server-side, and replaced by an opaque session id.
    """
    if cfg.PUBLIC_MODE or not authz.configured_roles((authz.ADMIN, authz.ISSUER)):
        raise HTTPException(status_code=404, detail="Not Found")
    # U14 F6: brake brute force before reading the token, so a script cannot
    # use the login form as an oracle for free.
    client = _client_ip(request)
    if not authz.login_allowed(client):
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-in attempts. Try again in 10 minutes.",
            headers={"Retry-After": str(authz.LOGIN_FAIL_WINDOW)})
    token = str((payload or {}).get("token") or "").strip()
    role = authz.resolve_role(token, (authz.ADMIN, authz.ISSUER))
    if role is None:
        authz.note_login_failure(client)
        return JSONResponse({"detail": "Invalid token."}, status_code=401)
    authz.clear_login_failures(client)
    sid = authz.create_staff_session(role)
    response.set_cookie(
        authz.STAFF_COOKIE, sid,
        max_age=authz.STAFF_SESSION_TTL,
        httponly=True,           # not readable from JS
        samesite="strict",       # no cross-site sends; paired with the origin check
        secure=cfg.PUBLIC_BASE_URL.startswith("https"),
        path="/",
    )
    return {"ok": True, "role": role}


@app.post("/staff/logout")
def staff_logout(request: Request, response: Response):
    authz.drop_staff_session(request.cookies.get(authz.STAFF_COOKIE))
    response.delete_cookie(authz.STAFF_COOKIE, path="/")
    return {"ok": True}


@app.post("/staff/logout/all")
def staff_logout_all(request: Request, response: Response):
    """Sign out every console session of the caller's role (U14 F6).

    Scoped to the role on purpose: an issuer clearing their own sessions must
    not knock an admin off the console.
    """
    role = authz.read_staff_session(request.cookies.get(authz.STAFF_COOKIE))
    if role is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    dropped = authz.drop_staff_sessions(role)
    response.delete_cookie(authz.STAFF_COOKIE, path="/")
    return {"ok": True, "role": role, "dropped": dropped}


@app.get("/api/staff/whoami")
def staff_whoami(request: Request,
                 x_admin_token: str | None = Header(default=None,
                                                    alias=authz.ROLE_HEADER)):
    """Which staff role this session (or header token) carries.

    U13 F4: the console rendered every ADMIN tab for every role, so an issuer
    saw issue/revoke/signer controls that 401 the moment they clicked. The
    console asks this once on boot and hides what the role cannot use.

    ``demo_open`` is reported explicitly: when no token is configured every
    role check passes, and the UI should say so instead of pretending auth is
    switched on.
    """
    if cfg.PUBLIC_MODE:
        return {"role": None, "public_mode": True, "demo_open": False,
                "session_seconds_left": None}
    demo_open = cfg.DEMO_OPEN and not authz.configured_roles(
        (authz.ADMIN, authz.ISSUER))
    role = authz.resolve_role(x_admin_token, (authz.ADMIN, authz.ISSUER))
    sid = request.cookies.get(authz.STAFF_COOKIE)
    if role is None:
        role = authz.read_staff_session(sid)
    if role is None and demo_open:
        role = authz.ADMIN
    return {"role": role, "public_mode": False, "demo_open": demo_open,
            "session_seconds_left": authz.staff_session_remaining(sid),
            # U24: the bucket key this caller is counted under. Staff-only, and
            # the only place an operator can check *which layer* decided the
            # client address: uvicorn's --proxy-headers rewrites the peer from
            # X-Forwarded-For before the app runs, which silently defeats the
            # app-level TRUSTED_PROXIES check.
            "client_ip": _client_ip(request)}


# U6.1: the portal is no longer a single self-contained index.html — CSS and the
# per-tab scripts are separate files, so they must be served. Before the split
# nothing was mounted, which is why this mount did not exist.
#
# U12 R0: mount the two asset directories explicitly instead of the whole
# static/ tree. Serving the directory root made every file under static/
# publicly downloadable, including index.html itself and the single-file
# rollback baseline (index.legacy.html), which carries the old prototype copy.
# Only /static/css and /static/js are reachable now; anything else 404s.
app.mount("/static/css", StaticFiles(directory=str(STATIC_DIR / "css")),
          name="static-css")
app.mount("/static/js", StaticFiles(directory=str(STATIC_DIR / "js")),
          name="static-js")


_INTEGRITY_TTL = 30
_integrity_cache = {"dir": None, "height": -1, "ts": 0.0, "ok": True, "bad": []}


def _integrity_view(ok: bool, bad: list, checked_at: float) -> dict:
    """Shape the integrity result, including *when* it was actually computed.

    U23: the check is cached for 30 s, so a caller could be looking at a
    verdict that is up to half a minute old without knowing it. ``checked_at``
    and ``age_s`` make the staleness readable instead of implied. Consumers that
    only care about the verdict keep using ``ok`` / ``bad_blocks``.
    """
    return {"ok": bool(ok), "bad_blocks": list(bad),
            "checked_at": round(checked_at, 1),
            "age_s": round(max(0.0, time.time() - checked_at), 1)}


def chain_integrity() -> dict:
    """Whether every block verifies, cached per chain dir + height (U15).

    A block signed by a signer that is no longer trusted still *reads*, but the
    whole-chain check fails, and every verdict built on it then reads INVALID —
    the loudest possible failure with the quietest possible cause. Surfacing it
    here means a broken demo is visible on /healthz instead of being discovered
    by a visitor. Re-checked at most every 30 s, and at once when the height
    changes.
    """
    chain = str(CHAIN_DIR)
    try:
        height = blockchain_util.last_height(chain)
    except (OSError, RuntimeError) as exc:
        return {**_integrity_view(False, [], time.time()), "error": str(exc)}
    now = time.time()
    cached = _integrity_cache
    if (cached["dir"] == chain and cached["height"] == height
            and now - cached["ts"] < _INTEGRITY_TTL):
        return _integrity_view(cached["ok"], cached["bad"], cached["ts"])
    try:
        ok, rows = blockchain_util.verify_chain(chain)
    except (OSError, RuntimeError) as exc:
        return {**_integrity_view(False, [], time.time()), "error": str(exc)}
    bad = [r.get("height") for r in rows if not r.get("ok")]
    cached.update({"dir": chain, "height": height, "ts": now,
                   "ok": bool(ok), "bad": bad})
    return _integrity_view(ok, bad, now)


@app.get("/healthz")
def healthz():
    """Liveness plus the dependency checks a demo deploy actually needs.

    ``status`` stays "ok" while the chain is readable — the per-dependency
    block says *what* is degraded instead of collapsing everything into one
    boolean, so a half-broken instance is diagnosable rather than opaque.
    """
    info = chain_service.chain_info()
    chain_dir_ok = os.access(CHAIN_DIR, os.W_OK) if CHAIN_DIR.exists() else False
    checks = {
        "chain_dir": {
            "path_exists": CHAIN_DIR.exists(),
            "writable": chain_dir_ok,
        },
        "storage": {
            "backend": cfg.STORAGE_BACKEND,
            "sqlite": (
                {"path_exists": Path(cfg.SQLITE_PATH).exists()}
                if cfg.STORAGE_BACKEND == "sqlite" else None
            ),
        },
        "chain": {
            "height": info.get("height"),
            "signers": info.get("num_signers", len(info.get("signers") or [])),
            # U15: every verdict depends on this; a false here explains a wall
            # of INVALID verdicts to anyone who looks.
            "integrity": chain_integrity(),
        },
        "static": {"dir_exists": STATIC_DIR.exists()},
        "observability": {
            "counters_shared_across_workers": obs.COUNTERS.shared_across_workers,
            "audit_events": len(audit.recent(limit=1)),
            # U24: an operator behind a proxy needs to know whether the real
            # client address is being used or the proxy's. Silent either way
            # is how a limiter that looks fine locks out a whole office.
            "client_ip_source": ("x-forwarded-for"
                                 if _proxy_nets()[0] else "peer"),
        },
        "config": {
            "fatal": len(CONFIG_REPORT["fatal"]),
            "warnings": len(CONFIG_REPORT["warnings"]),
        },
    }
    degraded = [name for name, ok in (
        ("chain_dir_writable", chain_dir_ok),
        ("static_dir", STATIC_DIR.exists()),
        ("chain_integrity", checks["chain"]["integrity"].get("ok", True)),
    ) if not ok]
    return {"status": "ok" if not degraded else "degraded", **info, "checks": checks}


@app.get("/api/diagnostics", dependencies=[Depends(_admin_required)])
def diagnostics():
    """The *why* behind /healthz: full config messages and integrity detail.

    U19: /healthz reported ``config: {fatal: 0, warnings: 1}`` and gave no way
    to read that one warning — the only recourse was grepping ``startup.py``
    for every branch that appends one. The counts stay public (they are cheap
    and reveal nothing); the text is staff-only, because it names directories
    and environment variables.
    """
    info = chain_service.chain_info()
    return {
        "version": cfg.APP_VERSION,
        "uptime_s": round(time.time() - _started_at, 1),
        "chain": {
            "name": info.get("chain_name"),
            "height": info.get("height"),
            "content_hash_algo": info.get("content_hash_algo"),
            "integrity": chain_integrity(),
            "signers": [
                {"name": s.get("name"), "ds_algo": s.get("ds_algo"),
                 "sha256fgpt": s.get("sha256fgpt"),
                 "retired_at_height": s.get("retired_at_height")}
                for s in (info.get("signers") or [])
            ],
        },
        "config": {
            "fatal": list(CONFIG_REPORT["fatal"]),
            "warnings": list(CONFIG_REPORT["warnings"]),
        },
        # U24: who counts as "the client" for rate limits and login lockouts.
        # Staff-only because it names internal network ranges.
        "client_ip": {
            "source": "x-forwarded-for" if _proxy_nets()[0] else "peer",
            "trusted_proxies": [str(net) for net in _proxy_nets()[0]],
            "invalid_entries": list(_proxy_nets()[1]),
        },
    }


@app.get("/api/metrics")
def metrics_endpoint():
    """Process-local counters: verification totals, verdict mix, denials.

    No PII and no hashes: endpoints are bucketed labels, not raw paths. The
    payload states that the counters are per-process rather than implying a
    cluster-wide number.
    """
    snapshot = obs.COUNTERS.snapshot()
    snapshot["chain_height"] = chain_service.chain_info().get("height")
    snapshot["public_mode"] = cfg.PUBLIC_MODE
    return snapshot


@app.get("/api/version")
def version_endpoint():
    """Verifier identity + chain snapshot reference, for verdict receipts and
    uptime checks. Public in both modes."""
    info = chain_service.chain_info()
    return {
        "app": "Gef26 credential verification portal",
        "version": cfg.APP_VERSION,
        "public_mode": cfg.PUBLIC_MODE,
        "ui_verify_only": cfg.UI_VERIFY_ONLY,
        # U13 F7: is this instance open because nobody configured a token?
        "demo_open": cfg.DEMO_OPEN and not authz.configured_roles(
            (authz.ADMIN, authz.ISSUER)),
        "public_base_url": PUBLIC_BASE_URL,
        "uptime_s": round(time.time() - _started_at, 1) if _started_at else None,
        "chain": {
            "name": info.get("chain_name"),
            "content_hash_algo": info.get("content_hash_algo"),
            "height": info.get("height"),
            "signers": info.get("num_signers", len(info.get("signers") or [])),
            # U15: the public page reads this to explain a wall of INVALID
            # verdicts, which would otherwise look like the holder's fault.
            "integrity": chain_integrity(),
        },
        "statuslist_digest": statuslist.build()[1].strip('"'),
    }


# --------------------------------------------------------------------------
# Core API
# --------------------------------------------------------------------------


@app.post("/api/issue", dependencies=[Depends(_admin_required)])
def issue(body: IssueBody):
    try:
        _validate_document_shape(body.document)
        result = chain_service.issue(body.document)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    doc_type = (body.document.get("DocumentInfo") or {}).get("DocType", "credential")
    notification = notifier.notify_issue(
        body.student_email, result["hashed_document"], doc_type)
    audit.record("issue", result["hashed_document"], "ok", doc_type)
    sid = str(((body.document.get("PersonalParticulars") or {})
               .get("StudentID")) or "")
    holder_path = None
    if sid:
        try:
            holder_path = "/me/" + capability.mint(sid,
                                                   result["hashed_document"])
        except (ValueError, RuntimeError):
            holder_path = None
    return {
        **result,
        "student_id": sid or None,
        "pdf_url": f"/api/pdf/{result['hashed_document']}",
        "credential_pdf_url": f"/api/admin/pdf/{result['hashed_document']}",
        "holder_path": holder_path,
        "notification": notification,
    }


@app.post("/api/issue/batch",
          dependencies=[Depends(authz.require_roles(authz.ADMIN, authz.ISSUER))])
def issue_batch(body: IssueBatchBody):
    """Issue up to ``BATCH_ISSUE_MAX`` credentials in one admin request.

    Rows are processed independently and continue past errors: each result
    row carries ``ok`` and, on failure, a human-readable ``error``. No
    rollback of successful rows when later rows fail.
    """
    creds = body.credentials
    if not creds:
        raise HTTPException(status_code=422,
                            detail="credentials must be a non-empty list.")
    if len(creds) > cfg.BATCH_ISSUE_MAX:
        raise HTTPException(
            status_code=422,
            detail=f"Too many rows ({len(creds)} > {cfg.BATCH_ISSUE_MAX}).")
    results = []
    ok_count = 0
    for row, item in enumerate(creds, start=1):
        document = item.document
        if not isinstance(document, dict):
            results.append({"row": row, "ok": False,
                            "error": "Row must contain a credential object."})
            continue
        try:
            _validate_document_shape(document)
            result = chain_service.issue(document)
        except ValueError as exc:
            results.append({"row": row, "ok": False, "error": str(exc)})
            continue
        except RuntimeError as exc:
            results.append({"row": row, "ok": False, "error": str(exc)})
            continue
        doc_type = (document.get("DocumentInfo") or {}).get("DocType", "credential")
        notification = notifier.notify_issue(
            item.student_email, result["hashed_document"], doc_type)
        # U13 F5: a batch is the moment links are needed in bulk. Mint the
        # holder link here (staff-only route anyway) and hand the student id
        # back, so the console can copy each link instead of hunting for it.
        sid = ((document.get("PersonalParticulars") or {}).get("StudentID") or "")
        holder_token = None
        if sid:
            try:
                holder_token = capability.mint(str(sid),
                                               result["hashed_document"])
            except (ValueError, RuntimeError):
                holder_token = None
        results.append({
            "row": row,
            "ok": True,
            "hashed_document": result["hashed_document"],
            "student_id": str(sid) or None,
            "height": result.get("height"),
            "pdf_url": f"/api/pdf/{result['hashed_document']}",
            "credential_pdf_url": f"/api/admin/pdf/{result['hashed_document']}",
            "qr_url": f"/api/qr/{result['hashed_document']}",
            "holder_path": ("/me/" + holder_token) if holder_token else None,
            "notification_status": (notification or {}).get("status", "skipped"),
        })
        ok_count += 1
    return {
        "summary": {"total": len(creds), "ok": ok_count,
                    "failed": len(creds) - ok_count},
        "results": results,
    }


# --------------------------------------------------------------------------
# Self-service credential maker (round 10): build + issue + sync files
# --------------------------------------------------------------------------


@app.post("/api/custom/build", dependencies=[Depends(_admin_required)])
async def custom_build(request: Request):
    """Fill in your own details -> build the credential, issue it on the
    chain (same admin guard as POST /api/issue), render a verifiable PDF and
    save the PDF + JSON into the main project directory.

    Body: any of surname / given_names / name, student_id, dob, sex, degree,
    degree_start, degree_end, honour, observations, issuer, issuer_unit,
    doc_type, date_of_issue, authorized_signature, plus ``issue`` (bool,
    default true). ``issue=false`` produces a draft file that verifies
    NOT FOUND until issued.
    """
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object.")
    try:
        body = CustomBuildBody.model_validate(payload)
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=422, detail="Body must be a JSON object.") from exc
    try:
        result = custom_service.build_outputs(
            body.model_dump(), cfg.PUBLIC_BASE_URL, issue=body.issue)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result


@app.get("/api/custom/list", dependencies=[Depends(_admin_required)])
def custom_list():
    """Generated self-service files, newest first (staff only, U13 F2)."""
    try:
        return {"files": custom_service.list_outputs(),
                "output_dir": str(custom_service._output_dir())}
    except (OSError, ValueError, KeyError, TypeError) as exc:  # never let listing break the UI
        return {"files": [], "output_dir": "", "error": str(exc)}


@app.get("/api/custom/file/{file_id}/{kind}",
         dependencies=[Depends(_admin_required)])
def custom_file(file_id: str, kind: str):
    """Serve a generated PDF or JSON from the sync dir (staff only, U13 F2)."""
    if kind not in ("pdf", "json"):
        raise HTTPException(status_code=404, detail="Unknown file kind.")
    try:
        path = custom_service.resolve_file(file_id, kind)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media = "application/pdf" if kind == "pdf" else "application/json"
    return FileResponse(path, media_type=media,
                        filename=f"{file_id}.{kind}")


@app.post("/api/revoke", dependencies=[Depends(_admin_required)])
def revoke(body: RevokeBody):
    if body.hashed_document is None and body.document is None:
        raise HTTPException(
            status_code=422,
            detail="Provide either hashed_document or the full document.",
        )
    if body.document is not None:
        try:
            _validate_document_shape(body.document)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    hashed_document = body.hashed_document or chain_service.hash_of(body.document)
    _validate_hash(hashed_document)
    # U16: effective_at dates the decision for the audit trail; it does not
    # schedule it. A future value used to be accepted silently and the
    # credential was revoked immediately, which reads as a broken promise.
    if body.effective_at is not None and body.effective_at > time.time() + 60:
        raise HTTPException(
            status_code=422,
            detail="effective_at cannot be in the future: a REVOKE takes effect "
                   "as soon as its block lands. The field records when the "
                   "decision was made, it does not schedule it.",
        )
    try:
        result = chain_service.revoke(hashed_document, reason=body.reason,
                                      effective_at=body.effective_at)
    except RuntimeError as exc:
        audit.record("revoke", hashed_document, "error", str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    audit.record("revoke", hashed_document, "ok",
                 f"height={result.get('height')}")
    return result


def _note_verification(result: dict, endpoint: str, height: int | None = None) -> None:
    """Count and log one verification decision.

    The log line carries the verdict and the chain height but never the full
    hash — ``redact`` truncates it to 8 characters, which is enough to
    correlate two lines about the same credential and useless as a lookup key.
    """
    verdict = result.get("verdict")
    obs.COUNTERS.record_verification(verdict)
    if height is None:
        height = result.get("height")
    if height is None:
        try:                       # chain height at decision time, for the log
            height = chain_service.chain_info().get("height")
        except RuntimeError:       # unreadable chain: verdict already says so
            height = None
    obs.log_event(
        "info", "verification",
        endpoint=endpoint, verdict=verdict, height=height,
        hashed_document=result.get("hashed_document"),
    )


@app.get("/api/verify/{hashed_document}")
def verify_hash(hashed_document: str):
    _validate_hash(hashed_document)
    result = chain_service.verify_hash(hashed_document)
    if result.get("verdict") == "REVOKED":
        result.update(chain_service.revoke_meta(hashed_document))
    result["receipt_id"] = receipt_registry.register(
        hashed_document, result.get("verdict"), time.time(), "verify/hash")
    verification_log.record(result.get("hashed_document"), result.get("verdict"))
    _note_verification(result, "verify/hash")
    return result


@app.get("/api/status/{hashed_document}")
def status(hashed_document: str):
    _validate_hash(hashed_document)
    try:
        return chain_service.status(hashed_document)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/verify/document")
async def verify_document_endpoint(request: Request):
    content_type = (request.headers.get("content-type") or "").lower()
    try:
        if content_type.startswith("application/json"):
            try:
                payload = await request.json()
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=422, detail="Invalid JSON.") from exc
            try:
                document = VerifyDocumentBody.model_validate(payload).document
            except PydanticValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail='JSON body must be {"document": {...}}.',
                ) from exc
        elif content_type.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise HTTPException(
                    status_code=422,
                    detail="multipart body must include a 'file' part.",
                )
            raw = await upload.read(MAX_UPLOAD_BYTES + 1)
            await upload.close()
            if len(raw) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds the {MAX_UPLOAD_BYTES} byte limit.",
                )
            document = _parse_upload(raw, upload.filename or "")
        else:
            raise HTTPException(
                status_code=415,
                detail="Send application/json or multipart/form-data.",
            )
        _validate_document_shape(document)
        result = chain_service.verify_document(document)
        if result.get("verdict") == "REVOKED":
            result.update(chain_service.revoke_meta(result.get("hashed_document") or ""))
        result["receipt_id"] = receipt_registry.register(
            result.get("hashed_document") or "", result.get("verdict"),
            time.time(), "verify/document")
        verification_log.record(result.get("hashed_document"), result.get("verdict"))
        _note_verification(result, "verify/document")
        return result
    except HTTPException:
        raise
    except RecursionError as exc:
        raise HTTPException(status_code=422, detail="JSON is too deeply nested.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON.") from exc


# --------------------------------------------------------------------------
# PDF auto-fill (round 9): extract a credential JSON draft from a PDF
# --------------------------------------------------------------------------


@app.post("/api/extract/pdf")
async def extract_pdf_endpoint(request: Request):
    """Auto-fill input assistance: upload a certificate PDF and get a
    credential JSON *draft* back for the form — never a verdict.

    - Portal-issued PDF (embedded credential.json)  -> mode=embedded_payload,
      byte-exact, confidence 1.0.
    - Text-layer electronic certificate             -> mode=text_extract,
      label-aware field extraction with per-field confidence + warnings.

    The result must be reviewed and submitted through the normal verify
    flow; nothing here bypasses the six cryptographic checks.
    """
    content_type = (request.headers.get("content-type") or "").lower()
    if not content_type.startswith("multipart/form-data"):
        raise HTTPException(
            status_code=415,
            detail="Send a PDF file as multipart/form-data ('file' part).")
    try:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(
                status_code=422,
                detail="multipart body must include a 'file' part.")
        raw = await upload.read(MAX_UPLOAD_BYTES + 1)
        await upload.close()
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Upload exceeds the {MAX_UPLOAD_BYTES} byte limit.")
        _require_pdf_magic(raw)
        result = pdf_extractor.extract_from_pdf(raw)
        result["extracted_at"] = int(time.time())
        result["note"] = ("自動填入僅供輸入輔助：結果需人手核對，並通過六項"
                          "密碼學檢查才獲得正式判定。")
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Employer pack (extras round 6): batch verify, status list, receipts, keys
# --------------------------------------------------------------------------


@app.post("/api/verify/batch")
async def verify_batch(request: Request):
    """Employer-pack batch verify: ``{"hashes": [...]}`` → per-row verdicts +
    summary. Every row is a normal verify_hash, and each result is registered
    in the receipt registry. Limit: ``cfg.MAX_BATCH_DOCUMENTS`` per call."""
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON.") from exc
    try:
        hashes = VerifyBatchBody.model_validate(payload).hashes
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=422, detail='Body must be {"hashes": [...]}.') from exc
    if not hashes:
        raise HTTPException(
            status_code=422, detail='Body must be {"hashes": [...]}.')
    if len(hashes) > cfg.MAX_BATCH_DOCUMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"Batch limit is {cfg.MAX_BATCH_DOCUMENTS} hashes.")

    counts = {"valid": 0, "revoked": 0, "not_found": 0, "invalid": 0, "error": 0}
    results: list[dict[str, object]] = []
    for row, h in enumerate(hashes):
        entry: dict[str, object] = {"row": row}
        if not isinstance(h, str):
            entry.update({"hashed_document": None, "verdict": "ERROR",
                          "error": "hash must be a string"})
            counts["error"] += 1
            results.append(entry)
            continue
        h = h.strip()
        entry["hashed_document"] = h
        if not HASH_RE.match(h):
            entry.update({"verdict": "INVALID HASH FORMAT",
                          "error": "not a base64url hash"})
            counts["error"] += 1
            results.append(entry)
            continue
        try:
            result = chain_service.verify_hash(h)
            if result.get("verdict") == "REVOKED":
                result.update(chain_service.revoke_meta(h))
            result["receipt_id"] = receipt_registry.register(
                h, result.get("verdict"), time.time(), "verify/batch")
            verdict = result.get("verdict") or "ERROR"
            obs.COUNTERS.record_verification(verdict)
            key = ("valid" if verdict == "VALID ON CHAIN"
                   else verdict.lower().replace(" ", "_").replace("/", "_"))
            counts[key] = counts.get(key, 0) + 1
            entry.update({
                "verdict": verdict,
                "chain_integrity": result.get("chain_integrity"),
                "signer_trusted": result.get("signer_trusted"),
                "on_chain_record": result.get("on_chain_record"),
                "hash_match": result.get("hash_match"),
                "signature_valid": result.get("signature_valid"),
                "not_revoked": result.get("not_revoked"),
                "receipt_id": result["receipt_id"],
                "reason": result.get("reason"),
                "effective_at": result.get("effective_at"),
            })
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            entry.update({"verdict": "ERROR", "error": str(exc)})
            counts["error"] += 1
        results.append(entry)
    obs.log_event("info", "verification_batch", endpoint="verify/batch",
                  total=len(hashes), **counts)
    return {"summary": {"total": len(hashes), **counts}, "results": results}


@app.post("/api/disclose/{hashed_document}")
async def disclose_endpoint(hashed_document: str, request: Request):
    """Build a disclosure view of a stored credential (batch U4.4).

    Body (all optional)::

        {"hide_sections": ["PersonalParticulars"],
         "hide_fields": ["PersonalParticulars.DOB"]}

    Omitted ``hide_sections`` hides the identity section. Sections are the unit
    that stays cryptographically checkable — hiding a *field* inside a
    disclosed section breaks that section's hash, and the view reports it in
    ``unbound_sections``.
    """
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    body = DiscloseBody.model_validate(payload)
    hide_sections = body.hide_sections
    if hide_sections is None:
        hide_sections = list(disclosure.DEFAULT_HIDDEN_SECTIONS)
    if not isinstance(hide_sections, list) or not all(
            isinstance(s, str) for s in hide_sections):
        raise HTTPException(status_code=422,
                            detail="hide_sections must be a list of strings.")
    hide_fields = body.hide_fields
    if hide_fields is not None and (not isinstance(hide_fields, list)
                                    or not all(isinstance(f, str) for f in hide_fields)):
        raise HTTPException(status_code=422,
                            detail="hide_fields must be a list of strings.")

    raw_path = CHAIN_DIR / "rawjsondocs" / f"{hashed_document}.json"
    try:
        doc = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=404,
            detail="No stored credential for that hash.") from exc
    try:
        return disclosure.make_disclosure(doc, hide_sections, hide_fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/verify/disclosure")
async def verify_disclosure_endpoint(request: Request):
    """Check a disclosure view against the on-chain credential.

    The disclosed sections must hash to the record's section hashes, and the
    Merkle root over them must equal the record's ``HashedDocument``. A view
    that fails this is reported, not trusted.
    """
    try:
        view = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON.") from exc
    if not isinstance(view, dict):
        raise HTTPException(status_code=422,
                            detail="Disclosure must be a JSON object.")

    credential = view.get("credential_hash")
    if not isinstance(credential, str) or not HASH_RE.match(credential):
        raise HTTPException(status_code=422,
                            detail="Disclosure has a malformed credential_hash.")

    record = chain_service.on_chain_payload(credential)
    if record is None:
        obs.COUNTERS.record_verification("NOT FOUND")
        obs.log_event("info", "verification_disclosure", endpoint="verify/disclosure",
                      verdict="NOT FOUND", ok=False,
                      hashed_document=credential)
        return {"ok": False, "reasons": ["credential is not on chain"],
                "bound_sections": [], "credential_on_chain": False,
                "chain_verdict": "NOT FOUND",
                "assurance": view.get("assurance")}

    report = disclosure.check_against_record(view, record)
    result = chain_service.verify_hash(credential)
    obs.COUNTERS.record_verification(result.get("verdict"))
    obs.log_event("info", "verification_disclosure", endpoint="verify/disclosure",
                  verdict=result.get("verdict"), ok=report["ok"],
                  hashed_document=credential)
    return {
        "ok": report["ok"],
        "reasons": report["reasons"],
        "bound_sections": report["bound_sections"],
        "credential_on_chain": True,
        "chain_verdict": result.get("verdict"),
        "assurance": view.get("assurance"),
    }


@app.get("/api/statuslist")
def statuslist_endpoint(request: Request):
    """Signed revocation status list (OCSP-like, cacheable)."""
    payload, etag = statuslist.build()
    headers = {"Cache-Control": "public, max-age=60", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=payload, headers=headers)


@app.get("/api/receipt/{receipt_id}")
def receipt_lookup(receipt_id: str):
    """Receipt registry: is this receipt one our verifier issued?"""
    if not re.match(r"^RCP-[0-9a-fA-F]+-[0-9A-F]{4}$", receipt_id):
        raise HTTPException(status_code=422, detail="Malformed receipt ID.")
    rec = receipt_registry.get(receipt_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    return rec


@app.get("/api/admin/apikeys", dependencies=[Depends(_admin_required)])
def list_apikeys():
    return {"keys": apikeys.list_keys()}


@app.post("/api/admin/apikeys", dependencies=[Depends(_admin_required)])
async def create_apikey(request: Request):
    """Create a public API key. The raw key is returned exactly once."""
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON.") from exc
    # Non-object bodies used to yield the default name; keep that behaviour.
    body = ApiKeyCreateBody.model_validate(payload if isinstance(payload, dict) else {})
    created = apikeys.create_key(body.name or "unnamed",
                                 _ttl_days(body.expires_in_days))
    audit.record("apikey.create", created["id"], "ok",
                 f"{created['name']} ttl={body.expires_in_days}")
    return created


@app.delete("/api/admin/apikeys/{kid}", dependencies=[Depends(_admin_required)])
def delete_apikey(kid: str, reason: str | None = None):
    if not apikeys.revoke_key(kid, reason):
        audit.record("apikey.revoke", kid, "not_found")
        raise HTTPException(status_code=404, detail="API key not found.")
    audit.record("apikey.revoke", kid, "ok", reason or "")
    return {"ok": True, "id": kid}


@app.post("/api/admin/apikeys/{kid}/rotate",
          dependencies=[Depends(_admin_required)])
def rotate_apikey(kid: str, expires_in_days: int | None = None):
    """Revoke ``kid`` and return a replacement secret (shown once)."""
    rotated = apikeys.rotate_key(kid, _ttl_days(expires_in_days))
    if rotated is None:
        audit.record("apikey.rotate", kid, "not_found")
        raise HTTPException(status_code=404,
                            detail="API key not found or already revoked.")
    audit.record("apikey.rotate", kid, "ok", f"-> {rotated['id']}")
    return rotated


@app.get("/api/admin/audit", dependencies=[Depends(_admin_required)])
def audit_trail(limit: int = cfg.AUDIT_RECENT_LIMIT):
    """Administrative actions (issuing, revoking, key/signer management).

    Separate from ``/api/log``: that one is the anonymised public record of
    verifications, this one records who changed what.
    """
    return {"events": audit.recent(max(1, min(limit, 500)))}


# --------------------------------------------------------------------------
# RAG chat (Week 2)
# --------------------------------------------------------------------------


@app.post("/api/chat")
def chat(body: ChatBody):
    try:
        return chat_service.answer(body.question, session_id=body.session_id,
                                   web=bool(body.web))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/chat/suggestions")
def chat_suggestions():
    return {"suggestions": chat_service.SUGGESTIONS}


@app.get("/api/rag/status")
def rag_status():
    return chat_service.rag_status()


# --------------------------------------------------------------------------
# Demo helpers
# --------------------------------------------------------------------------


@app.get("/api/demo/credentials")
def demo_credentials():
    creds = chain_service.demo_credentials()  # dict: kind -> {document, hashed_document}
    if cfg.PUBLIC_MODE:
        # landing-page REVOKED sample (issued + revoked on this chain)
        revoked_hash = chain_service.ensure_revoked_sample()
        creds["revoked_sample"] = {
            "hashed_document": revoked_hash,
            "document": chain_service.SAMPLE_REVOKED_DOC,
        }
    return creds


# --------------------------------------------------------------------------
# Post-Week-3 extras: QR, public log, anomaly watch
# --------------------------------------------------------------------------


@app.get("/verify")
def verify_page():
    """Scan target for QR codes: the same UI, auto-verifying ?hash=..."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/qr/{hashed_document}")
def qr(hashed_document: str):
    """PNG QR code encoding the public verification URL for this hash."""
    _validate_hash(hashed_document)
    url = f"{PUBLIC_BASE_URL}/verify?hash={hashed_document}"
    try:
        import qrcode
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="QR support not installed (pip install qrcode).",
        ) from exc
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/log")
def public_log_endpoint():
    """Anonymized recent verifications + the append-only chain tail."""
    try:
        return {
            "verifications": verification_log.recent(),
            "total_verifications": verification_log.total(),
            "chain_events": chain_service.chain_tail(limit=cfg.CHAIN_TAIL_LIMIT),
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/anomalies")
def anomalies_endpoint():
    """Signer-velocity anomalies (IsolationForest + rule fallback) + chart."""
    try:
        return anomaly.detect(str(CHAIN_DIR))
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Extras round 2: verifiable PDF, student lookup, signer admin, notifications
# --------------------------------------------------------------------------


def _credential_pdf(hashed_document: str, redact: bool) -> Response:
    """Render the PDF for one hash, in either the full or the redacted form.

    U13 F1: a hash is a public identifier, not a credential. The public route
    gets ``redact=True`` (identity withheld, no embedded JSON); the full file
    is served only to the holder (capability link) or to staff.
    """
    _validate_hash(hashed_document)
    raw_path = CHAIN_DIR / "rawjsondocs" / f"{hashed_document}.json"
    if not raw_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No raw document on file for this hash (samples are "
                   "available; issue new credentials to get their PDFs).",
        )
    try:
        document = json.loads(raw_path.read_text(encoding="utf-8"))
        # U14: a PDF is static, so the chain state has to be painted onto it.
        try:
            revocation = chain_service.revoke_meta(hashed_document) or None
        except RuntimeError:
            revocation = None
        data = pdf_diploma.render_diploma_pdf(
            document, hashed_document, PUBLIC_BASE_URL, redact=redact,
            revocation=revocation, integrity=chain_integrity())
    except (OSError, ValueError, TypeError, KeyError) as exc:  # rendering is self-contained; never 500
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    stem = "verification" if redact else "credential"
    cache = "public, max-age=3600" if redact else "no-store"
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{stem}-{hashed_document[:12]}.pdf"',
        "Cache-Control": cache,
    })


@app.get("/api/pdf/{hashed_document}")
def diploma_pdf(hashed_document: str):
    """Download the redacted verification report for an on-chain hash.

    Identity fields are withheld and the embedded JSON is dropped: the report
    proves *what* the chain says, not *who* holds it. The full credential PDF
    is at ``/api/me/{cap}/pdf`` (holder) and ``/api/admin/pdf/{hash}`` (staff).
    """
    return _credential_pdf(hashed_document, redact=True)


@app.get("/api/admin/pdf/{hashed_document}",
         dependencies=[Depends(_admin_required)])
def admin_credential_pdf(hashed_document: str):
    """Staff: the full credential PDF (re-issue, archive, dispute handling)."""
    return _credential_pdf(hashed_document, redact=False)


@app.post("/api/me/{cap}/renew")
def holder_renew(cap: str):
    """Extend a holder link without asking the office (U14).

    Only in the last week of its life: renewing early would merely widen the
    window in which a leaked link works. The old token is left valid until its
    own expiry, so a holder who renews does not break the link they already
    sent to an employer.
    """
    payload = capability.parse(cap)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="This link is invalid or has expired. Ask the issuer for a "
                   "new one.")
    remaining = payload["exp"] - int(time.time())
    if remaining > cfg.CAPABILITY_RENEW_WINDOW:
        raise HTTPException(
            status_code=403,
            detail=f"This link still has {remaining // 86400} day(s) left. "
                   "Renewal opens in the last 7 days, so a working link is "
                   "never extended early.")
    try:
        result = chain_service.student_credentials(payload["sid"])
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not any(c["hashed_document"] == payload["h"]
               for c in result["credentials"]):
        raise HTTPException(status_code=404,
                            detail="This link is invalid or has expired.")
    token = capability.mint(payload["sid"], payload["h"])
    renewed = capability.parse(token) or {}
    return {
        "capability": token,
        "path": f"/me/{token}",
        "expires_at": renewed.get("exp"),
        "previous_expires_at": payload["exp"],
    }


@app.get("/api/me/{cap}/pdf")
def holder_pdf(cap: str):
    """Holder: the full credential PDF, only through a signed link.

    A bad, expired or offset token answers the same 404 as the page, so the
    route never confirms that a link used to exist.
    """
    payload = capability.parse(cap)
    if payload is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return _credential_pdf(payload["h"], redact=False)


@app.get("/me/{cap}")
def me_page(cap: str):
    """U12 R3: holder page, reachable only through a signed link.

    A bad or expired token and a token for a credential that no longer exists
    both answer 404 — the page must not confirm that a link "used to work".
    """
    if capability.parse(cap) is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(STATIC_DIR / "holder.html")


@app.get("/api/me/{cap}")
def me_credentials(cap: str):
    """The one credential a capability link points at, plus its live status."""
    payload = capability.parse(cap)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="This link is invalid or has expired. Ask the issuer for a "
                   "new one.")
    try:
        result = chain_service.student_credentials(payload["sid"])
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    rows = [c for c in result["credentials"]
            if c["hashed_document"] == payload["h"]]
    if not rows:
        raise HTTPException(status_code=404,
                            detail="This link is invalid or has expired.")
    # U13 F3: a holder should be told *why* their credential was revoked, not
    # only that it was. One chain scan, then decorate the rows in place.
    if any(c.get("revoked") for c in rows):
        try:
            revocations = {r["hash"]: r for r in chain_service.revoked_records()}
        except RuntimeError:
            revocations = {}
        for c in rows:
            rec = revocations.get(c["hashed_document"]) or {}
            c["revoked_reason"] = rec.get("reason")
            c["revoked_height"] = rec.get("height")
            c["revoked_effective_at"] = rec.get("effective_at")
    return {
        "student_id": payload["sid"],
        "expires_at": payload["exp"],
        "credentials": rows,
    }


@app.get("/api/holder-link", dependencies=[Depends(_admin_required)])
def holder_link(student_id: str, hashed_document: str):
    """Staff-side minting: turn a student's credential into a holder link.

    Staff-only on purpose. Minting is the moment a link comes into existence,
    so it belongs behind the same auth as issuing.
    """
    if not student_id or not hashed_document:
        raise HTTPException(status_code=422,
                            detail="student_id and hashed_document are required.")
    token = capability.mint(student_id, hashed_document)
    return {
        "token": token,
        "path": "/me/" + token,
        "expires_in": cfg.CAPABILITY_TTL,
    }


@app.get("/api/signers")
def signers_list():
    try:
        return chain_service.list_signers()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/signers/keys")
def signers_keys():
    """Public keys + retirement boundaries — the offline trust anchor (U17).

    Public by design: a public key is public. A verifier that cached a status
    list needs this to check its signature without asking the portal again, and
    the fingerprint in the signature tells it which entry to use.
    """
    try:
        payload = chain_service.public_keys()
        info = chain_service.chain_info()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    payload["chain"] = {
        "name": info.get("chain_name"),
        "height": info.get("height"),
        "content_hash_algo": info.get("content_hash_algo"),
    }
    return payload


@app.post("/api/signers", dependencies=[Depends(_admin_required)])
def signers_add(body: AddSignerBody):
    try:
        result = chain_service.add_signer(body.name.strip() or "NEW SIGNER",
                                          body.ds_algo.strip())
    except ValueError as exc:
        audit.record("signer.add", body.name, "error", str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        audit.record("signer.add", body.name, "error", str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    audit.record("signer.add", result.get("sha256fgpt"), "ok", body.ds_algo.strip())
    return result


@app.post("/api/signers/active", dependencies=[Depends(_admin_required)])
def signers_activate(body: ActiveSignerBody):
    try:
        result = chain_service.set_active_signer(body.sha256fgpt)
    except ValueError as exc:
        audit.record("signer.activate", body.sha256fgpt, "error", str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        audit.record("signer.activate", body.sha256fgpt, "error", str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    audit.record("signer.activate", body.sha256fgpt, "ok")
    return result


@app.post("/api/signers/retire", dependencies=[Depends(_admin_required)])
def signers_retire(body: RetireSignerBody):
    """Retire a signer without deleting it (U16).

    Deleting an entry was how a demo chain became unverifiable: one block was
    signed by a key that then vanished from ``info.yaml``, and because
    ``chain_integrity`` is one of the six checks every verdict read INVALID.
    Retirement records a height boundary instead, so the blocks that key already
    signed stay valid.
    """
    try:
        result = chain_service.retire_signer(body.sha256fgpt)
    except ValueError as exc:
        audit.record("signer.retire", body.sha256fgpt, "error", str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        audit.record("signer.retire", body.sha256fgpt, "error", str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    audit.record("signer.retire", body.sha256fgpt, "ok",
                 f"retired_at=#{result.get('retired_at_height')}")
    return result


@app.get("/api/notifications", dependencies=[Depends(_admin_required)])
def notifications_list():
    """Recently recorded notifications (staff only, U13 F2)."""
    return {"notifications": notifier.recent_notifications(10)}


@app.get("/api/admin/chain-snapshot", dependencies=[Depends(_admin_required)])
def chain_snapshot():
    """Signed snapshot manifest: identity, height, tip hash, algo, signer set."""
    try:
        return chain_service.snapshot_manifest()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Upload parsing
# --------------------------------------------------------------------------


def _parse_upload(raw: bytes, filename: str) -> dict:
    """Parse an uploaded credential.

    Two supported forms:
    - a portal-issued diploma PDF (embeds the exact credential JSON — verified
      with no OCR);
    - a .json / .txt file (or pasted JSON text) with the credential fields.

    The chain verifies exact JSON values, so only these exact forms produce
    meaningful verdicts.
    """
    lower = (filename or "").lower()
    if lower.endswith(".pdf") or b"%PDF" in raw[:1024]:
        return pdf_diploma.extract_credential(raw)
    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not lower.endswith((".json", ".txt")) and not text.startswith("{"):
        raise ValueError("Unsupported file type — upload a .json credential "
                         "or a portal-issued diploma PDF.")
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError("The credential must be a JSON object.")
    return document
