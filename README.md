# GEF Mobile — Post-Quantum Credential Verification Portal (P14)

A small university registrar system that issues, verifies and revokes academic
credentials, with every issuance written into a hash chain. Signatures use
ML-DSA-65 (post-quantum) plus RSA-PSS/ECDSA for the registrar office, and the
checking side is usable by someone with no account and no browser extension:
paste a code, drop a signed PDF, and get one plain sentence back.

## Live demo (evaluators)

Current address: `https://rankings-pty-jenny-remained.trycloudflare.com`

The address changes every time the launcher restarts (a quick tunnel has no
fixed hostname), so on the day read `verification-portal/showcase-url.txt` —
`start_showcase.bat` writes it there and prints it.

- `/` — one-screen verification (paste a code, or choose a PDF)
- `/issue` — three-field issuance page (name / student ID / degree)
- `/showtime` — the four-step stage used at the project showcase
- `/portal` — the full original portal (registrar, student, AI assistant, log)

The demo runs on a laptop behind a temporary Cloudflare tunnel, so the URL only
lives while that machine is awake. If it is down, the local path is:

```bash
cd verification-portal
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8013 --no-proxy-headers
```

## Layout

- `verification-portal/` — the working product (FastAPI backend, static frontend,
  tests, docs). Start here: [`verification-portal/README.md`](verification-portal/README.md)
- `demo-media/` — demo video and posters used in the submission
- `P14-A0-Poster.pptx` — the A0 poster (841 x 1189 mm, one page, two QR codes);
  `P14-A0-Poster.pdf` is the same page at 150 dpi for the print shop, and
  `P14-A0-Poster-preview.png` is it at a third of the size
- `slides_work_v2/` — deck/summary build scripts (`poster.html` is the poster
  source; `poster_qr.py` and `build_poster_pptx.py` regenerate the codes and
  the deck)
- `original-repo/` — the Gef26 hash-chain repo this was built on
- `USAGE.md`, `CODE_WALKTHROUGH.md`, `SUBMISSION_PLAN.md` — usage guide,
  per-code-block walkthrough and submission plan

## What it does

1. **Issue** — staff signs a credential (ML-DSA-65 + a second signer), writes it
   to the hash chain, and hands back a PDF and a short verification code.
2. **Verify** — the code or the PDF's embedded payload is checked on six axes:
   signature, chain position, hash match, revocation status, issuer trust, age.
   The result is one line: valid / revoked / not found / unverifiable.
3. **Revoke** — a revocation entry is appended; the PDF still verifies
   cryptographically but now reports as revoked, which is the point of a
   status list rather than a re-signed document.
4. **Offline / bulk** — signed status list and batch verification for employers,
   plus an offline verifier that only needs the PDF and the public key.

## Notes

- No private keys, chain state or virtualenv are committed; `data/` is ignored
  and is re-seeded on first start with demo keys.
- Everything here runs offline: no paid APIs, no cloud dependencies, no
  telemetry.
- This is a course project, not a production registrar system. The honest
  limits (single-process chain writes, demo keys, temporary tunnel) are written
  down in `verification-portal/docs/U26_showcase.md` and
  `verification-portal/docs/U25_one_screen.md`.
