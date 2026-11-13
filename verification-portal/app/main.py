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

import json
import re
import time

from contextlib import asynccontextmanager
from io import BytesIO

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from . import (anomaly, apikeys, chain_service, chat_service, config as cfg,
               custom_service, notifier, pdf_diploma, pdf_extractor,
               receipt_registry, statuslist)
from .config import (
    ADMIN_TOKEN,
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
    ChatBody,
    IssueBatchBody,
    IssueBody,
    RevokeBody,
)

HASH_RE = re.compile(r"^[A-Za-z0-9_-]{16,200}$")
SIX_CHECKS = ("chain_integrity", "signer_trusted", "on_chain_record",
              "hash_match", "signature_valid", "not_revoked")

_public_limiter = SlidingWindowLimiter()
_admin_limiter = SlidingWindowLimiter()
_EXEMPT_PATHS = {"/", "/healthz", "/api/version"}
_started_at = time.time()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if cfg.CHAIN_SNAPSHOT_URL:
        chain_service.restore_snapshot_if_needed(cfg.CHAIN_SNAPSHOT_URL)
    chain_service.ensure_chain()
    yield


app = FastAPI(title="Credential Verification Portal", version="1.0.0",
              lifespan=_lifespan)


@app.middleware("http")
async def _hardening_middleware(request: Request, call_next):
    """Request-body cap + per-IP sliding-window rate limiting.

    Requests with a valid ``Authorization: Bearer <api-key>`` get a per-key
    bucket at API_KEY_MAX (the "public verification API"); anonymous web
    traffic stays on the shared per-IP bucket.
    """
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413,
                            content={"detail": "Request body too large."})

    if RATE_LIMIT_ENABLED and request.url.path not in _EXEMPT_PATHS:
        auth = request.headers.get("authorization", "")
        api_key = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        keyed = None
        if api_key:
            keyed = apikeys.validate_key(api_key)
            if keyed is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or revoked API key."},
                )
        forwarded = request.headers.get("x-forwarded-for", "")
        key = "apikey:" + keyed["id"] if keyed else (
            forwarded.split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))
        admin = request.url.path.startswith(("/api/issue", "/api/revoke"))
        limiter = _admin_limiter if admin else _public_limiter
        limit = (RATE_LIMIT_ADMIN_MAX if admin
                 else (cfg.API_KEY_MAX if keyed else RATE_LIMIT_PUBLIC_MAX))
        if not limiter.allow(key, limit):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded — try again shortly."},
            )
    return await call_next(request)


def _admin_required(x_admin_token: str | None = Header(default=None)):
    if cfg.PUBLIC_MODE:
        raise HTTPException(
            status_code=403,
            detail="Admin functions are disabled in public verifier mode. "
                   "Run a private instance (PUBLIC_MODE=0) behind auth to issue "
                   "or revoke credentials.")
    if ADMIN_TOKEN and x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401,
                            detail="Missing or invalid X-Admin-Token header.")


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
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz():
    info = chain_service.chain_info()
    return {"status": "ok", **info}


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
        "public_base_url": PUBLIC_BASE_URL,
        "uptime_s": round(_started_at, 1) if _started_at else None,
        "chain": {
            "name": info.get("chain_name"),
            "content_hash_algo": info.get("content_hash_algo"),
            "height": info.get("height"),
            "signers": info.get("num_signers", len(info.get("signers") or [])),
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
    return {
        **result,
        "pdf_url": f"/api/pdf/{result['hashed_document']}",
        "notification": notification,
    }


@app.post("/api/issue/batch", dependencies=[Depends(_admin_required)])
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
        results.append({
            "row": row,
            "ok": True,
            "hashed_document": result["hashed_document"],
            "height": result.get("height"),
            "pdf_url": f"/api/pdf/{result['hashed_document']}",
            "qr_url": f"/api/qr/{result['hashed_document']}",
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
        result = custom_service.build_outputs(
            payload, cfg.PUBLIC_BASE_URL, issue=payload.get("issue", True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result


@app.get("/api/custom/list")
def custom_list():
    """Generated self-service files, newest first."""
    try:
        return {"files": custom_service.list_outputs(),
                "output_dir": str(custom_service._output_dir())}
    except Exception as exc:  # never let listing break the UI
        return {"files": [], "output_dir": "", "error": str(exc)}


@app.get("/api/custom/file/{file_id}/{kind}")
def custom_file(file_id: str, kind: str):
    """Serve a generated PDF or JSON from the sync dir (path-safe)."""
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
    try:
        return chain_service.revoke(hashed_document, reason=body.reason,
                                    effective_at=body.effective_at)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/verify/{hashed_document}")
def verify_hash(hashed_document: str):
    _validate_hash(hashed_document)
    result = chain_service.verify_hash(hashed_document)
    if result.get("verdict") == "REVOKED":
        result.update(chain_service.revoke_meta(hashed_document))
    result["receipt_id"] = receipt_registry.register(
        hashed_document, result.get("verdict"), time.time(), "verify/hash")
    verification_log.record(result.get("hashed_document"), result.get("verdict"))
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
            payload = await request.json()
            document = payload.get("document") if isinstance(payload, dict) else None
            if not isinstance(document, dict):
                raise HTTPException(
                    status_code=422,
                    detail='JSON body must be {"document": {...}}.',
                )
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
        if raw.lstrip()[:4] != b"%PDF":
            raise HTTPException(
                status_code=422,
                detail="仅支持 PDF 文件。请上传证书 PDF（.pdf）。")
        result = pdf_extractor.extract_from_pdf(raw)
        result["extracted_at"] = int(time.time())
        result["note"] = ("自动填充仅供输入辅助：结果需人工核对，并通过六项"
                          "密码学检查获得正式判定。")
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
    in the receipt registry. Limit: 500 hashes per call."""
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON.") from exc
    hashes = payload.get("hashes") if isinstance(payload, dict) else None
    if not isinstance(hashes, list) or not hashes:
        raise HTTPException(
            status_code=422, detail='Body must be {"hashes": [...]}.')
    if len(hashes) > 500:
        raise HTTPException(status_code=422, detail="Batch limit is 500 hashes.")

    counts = {"valid": 0, "revoked": 0, "not_found": 0, "invalid": 0, "error": 0}
    results = []
    for row, h in enumerate(hashes):
        entry = {"row": row}
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
        except Exception as exc:  # noqa: BLE001 — corrupted chain etc.
            entry.update({"verdict": "ERROR", "error": str(exc)})
            counts["error"] += 1
        results.append(entry)
    return {"summary": {"total": len(hashes), **counts}, "results": results}


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
    name = payload.get("name") if isinstance(payload, dict) else None
    return apikeys.create_key(name or "unnamed")


@app.delete("/api/admin/apikeys/{kid}", dependencies=[Depends(_admin_required)])
def delete_apikey(kid: str):
    if not apikeys.revoke_key(kid):
        raise HTTPException(status_code=404, detail="API key not found.")
    return {"ok": True, "id": kid}


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
            "chain_events": chain_service.chain_tail(limit=10),
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


@app.get("/api/pdf/{hashed_document}")
def diploma_pdf(hashed_document: str):
    """Download a portal-issued diploma PDF for an on-chain hash.

    Renders the credential as a printable card and embeds the exact JSON, so
    the PDF itself can later be verified (no OCR).
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
        data = pdf_diploma.render_diploma_pdf(
            document, hashed_document, PUBLIC_BASE_URL)
    except Exception as exc:  # rendering is self-contained; never 500
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=\"credential-{hashed_document[:12]}.pdf\"",
        "Cache-Control": "public, max-age=3600",
    })


@app.get("/api/student/{student_id}")
def student_lookup(student_id: str, dob: str | None = None):
    """Self-service: a student's own credentials (issuer-side registry).

    Requires the exact DOB to reveal anything — a minimal privacy gate for the
    demo. The chain itself stores only hashes; the portal's rawjsondocs/ is the
    issuer's lookup index.
    """
    if not student_id or len(student_id) > 40:
        raise HTTPException(status_code=422, detail="Invalid StudentID.")
    if not dob:
        # privacy gate: never reveal whether a StudentID exists without the DOB
        raise HTTPException(
            status_code=404,
            detail="DOB is required to look up a student's credentials.",
        )
    try:
        result = chain_service.student_credentials(student_id, dob)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result["credentials"]:
        raise HTTPException(
            status_code=404,
            detail="No credential found for this Student ID + DOB.",
        )
    return result


@app.get("/api/signers")
def signers_list():
    try:
        return chain_service.list_signers()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/signers", dependencies=[Depends(_admin_required)])
def signers_add(body: AddSignerBody):
    try:
        return chain_service.add_signer(body.name.strip() or "NEW SIGNER",
                                        body.ds_algo.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/signers/active", dependencies=[Depends(_admin_required)])
def signers_activate(body: ActiveSignerBody):
    try:
        return chain_service.set_active_signer(body.sha256fgpt)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/notifications")
def notifications_list():
    """Recently recorded notifications (dry-run emails included)."""
    return {"notifications": notifier.recent_notifications(10)}


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
    if lower.endswith(".pdf") or raw.lstrip()[:4] == b"%PDF":
        return pdf_diploma.extract_credential(raw)
    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not lower.endswith((".json", ".txt")) and not text.startswith("{"):
        raise ValueError("Unsupported file type — upload a .json credential "
                         "or a portal-issued diploma PDF.")
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError("The credential must be a JSON object.")
    return document
