# 3-minute demo script + pilot + judge Q&A

## Demo script (screen recording, ~3 minutes)

- **0:00–0:30 — The pain.** "Verifying a foreign degree takes 10 days and
  $200. Universities close; students lose their records; employers waste
  weeks calling registrars."
- **0:30–1:30 — The solution.** Open the deployed URL. Click the **VALID**
  sample. Six checks pass in seconds → verdict `VALID ON CHAIN`. Click the
  **REVOKED** sample → `REVOKED` with the revocation metadata. Click the
  **INVALID** (not-found) sample → `NOT FOUND`. Show the **Download receipt**
  button on the verdict card.
- **1:30–2:30 — The employer pack.** Open a terminal. Run
  `python scripts/batch_verify.py --csv candidates.csv --out results.csv
  --api https://<your-url>` on 5 hashes. Show the results CSV: per-row
  verdicts, receipt IDs, summary row. Show `GET /api/statuslist` (signed
  revocation status list) returning a payload + signature.
- **2:30–3:00 — The close.** "The tech is done — 89 tests green, restart
  persistence proven. What's left is coordination: one registrar to run a
  pilot."

## The three questions judges will ask

1. **"Why blockchain and not a database?"**
   "Because a database dies when the university closes. A chain persists —
   append-only, signed blocks; anyone can replay it. We store only hashes
   and signatures, so there is nothing valuable to leak."
2. **"Why ML-DSA?"**
   "Credentials live for 50 years. RSA/ECDSA will be broken by quantum
   computers in that window; ML-DSA (FIPS 204) is the post-quantum standard
   already in this codebase."
3. **"How do you make money?"**
   "We don't. We prove the standard works so an incumbent vendor (Parchment,
   WES, Digitary) can adopt the issuer/verifier spec. The pilot is about
   validation, not revenue."

## Pilot script (one real registrar, 30 minutes)

1. Issue a CSV batch of 5–20 sample/consented credentials (CLI or admin tab).
2. Verify the PDFs back — expect VALID.
3. Revoke one credential — expect REVOKED.
4. Collect: time-to-verify, false mismatches, confusing steps, missing fields.
5. Ask: *"Would you use this instead of calling the registrar's office?"*
