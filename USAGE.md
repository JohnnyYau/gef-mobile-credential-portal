# GEF-mobile — Credential Verification Portal · User Manual

> **One line:** a web portal where a student uploads their diploma, the portal
> extracts the fields, verifies them against a signed blockchain, and shows a
> verdict with six checks explained — plus an AI assistant that can pull
> person context and (optionally) search the web.

This manual covers the **verification-portal/** application (the web product)
and the **original-repo/** library it wraps (the blockchain core).

---

## 1. What you get

```
GEF-mobile-project/
├── original-repo/          # The blockchain core you originally uploaded
│   └── (JSONSTRUCTURE.md, blockchain_util.py, crypto_util.py, tests, ...)
└── verification-portal/    # The product: FastAPI backend + web UI + CLI tools
    ├── app/                # backend package (main.py = the API)
    ├── static/index.html   # the single-page UI (no build step, bilingual, role-based)
    ├── scripts/            # CLI tools (batch verify, chain backup, test runner)
    ├── tests/              # 12 test modules, all green
    ├── start_portal.bat    # one-click launcher (Windows)
    ├── start_portal.sh     # one-click launcher (macOS/Linux)
    ├── docs/               # deploy guide, demo script, registrar outreach
    ├── render.yaml         # Render blueprint (public verifier mode)
    ├── railway.toml        # Railway blueprint
    └── demo.mp4            # 3-minute demo video
```

Self-issued credentials (round 10) are synced to `自制凭证-outputs/` **next to
this project folder** (the main project directory), one `*.pdf` + `*.json`
pair per credential.

**What it does end to end**

1. A registrar (admin) issues a credential — the portal hashes the document,
   writes an `ISSUE` block signed with a post-quantum **ML-DSA-65** key, and
   returns a `HashedDocument` + a verifiable PDF + a QR code.
2. A holder shares the PDF / hash / QR.
3. Anyone (no account, no wallet, no node) opens the portal, uploads the PDF
   or pastes the hash, and gets a verdict with six checks + a downloadable
   receipt in seconds.

---

## 2. System requirements

- **Python 3.11+** (tested on 3.13). Python 3.10 may work but is not tested.
- Any OS (Windows, macOS, Linux). Commands below are given for PowerShell and
  bash; the app itself is cross-platform.
- ~2 GB free disk for a comfortable install (the heavy optional RAG deps).

---

## 3. Quick start

**The easiest way (one click):** double-click `start_portal.bat` (Windows) or
run `./start_portal.sh` (macOS/Linux) inside `verification-portal/`. First run
creates the virtualenv, installs dependencies, seeds the demo chain and opens
the portal in your browser. Later runs just start the server. Default is
private mode (everything enabled).

**Two launchers (round 10)** — same codebase, different face:

| File | Mode | Tabs you see |
|---|---|---|
| `start_portal_admin.bat` | **Issue / admin side** (default) | all: 开始, 验证, 学生, AI 助手, 日志, **自制**, 签发, 注销, 签发方 |
| `start_portal_verify.bat` | **Verify-only side** | just 验证, AI 助手, 日志 |

Both serve on `http://127.0.0.1:8000` — run one at a time. The difference is
one environment variable: `UI_VERIFY_ONLY=1` (verify side) vs `0`/unset
(admin side). `PUBLIC_MODE=1` additionally disables the admin API endpoints
(403) for a true public deployment.

Manual equivalent:

```powershell
cd verification-portal
py -m venv .venv
.\.venv\Scripts\Activate.ps1        # bash: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --no-proxy-headers   # http://127.0.0.1:8000
```

`--no-proxy-headers` is not optional. Uvicorn trusts `X-Forwarded-For` by
default (from 127.0.0.1), rewriting the caller address before the app sees it —
which defeats the app's own `TRUSTED_PROXIES` check, so a forged header picks
a fresh rate-limit bucket and the login lockout never engages. If the portal
really sits behind a proxy, start it with that proxy's address in
`--forwarded-allow-ips` *and* the same address in `TRUSTED_PROXIES`.

Open **http://127.0.0.1:8000**. The portal boots in **private mode** by
default (all tabs visible, including Issue/Revoke). The landing page offers
three role entries (验证学历 / 我是学生 / 我是学校管理员), and the sample
buttons work immediately.

To run the **public verifier mode** (the deployed shape — admin endpoints
403, admin tabs hidden, amber banner shown):

```powershell
$env:PUBLIC_MODE="1"
uvicorn app.main:app --reload --no-proxy-headers
```

> The portal **auto-seeds a demo chain** on first boot (sample diploma +
> transcript + a revoked sample), so the UI is usable immediately.

### After a restart: the ten-second check

```powershell
python scripts/smoke_portal.py --base http://127.0.0.1:8000 --admin-token <staff-token>
```

22 read-only assertions across the public and staff surfaces (health, version,
verify, both PDF forms, the QR actually being embedded, holder link, renewal
refusal, `GET /api/diagnostics` with and without a credential, the integrity
verdict's age, which address the limiter counts, and whether a forged
`X-Forwarded-For` changes the peer). It prints `PASS`/`FAIL` per line and exits
non-zero on any failure. Drop `--admin-token` to skip the staff half on a
public instance.

`GET /healthz` also reports `checks.chain.integrity`. If that is `false` the
top-level status becomes `degraded`, every verdict reads INVALID, and the fault
is the chain (a block whose signer is no longer trusted), not the credential.
Since U19 a PDF generated while the chain is broken says so on the page
(`CHAIN INTEGRITY FAILED: block #N.`), because a printed report cannot be fixed
later.

The integrity check is cached for 30 seconds, so since U23 the block also
carries `checked_at` (epoch seconds) and `age_s`: a `true` that is 25 seconds
old is not the same claim as a `true` computed now. A cache hit keeps the
original `checked_at` — if it were refreshed on read, the field would always
read `0.0` and mean nothing. If a scan takes longer than the TTL, the verdict is
not cached at all (an entry that expires while it is being written could never
be read).

`GET /healthz` only gives you the *count* of config problems
(`config: {fatal: 0, warnings: 1}`). The text lives behind a staff-only
`GET /api/diagnostics` (U19), which returns the messages in full plus chain
integrity, signer retirement heights and `uptime_s`. Use `X-Admin-Token` or a
staff session cookie.

### Private (admin) mode, explicitly

Set `PUBLIC_MODE=0` (default) to get the full UI — verify, student, chat,
log plus the admin tabs (issue, revoke, signers, self-issue).

**Verify-only UI** (`UI_VERIFY_ONLY=1`): trims the web UI to just the three
tabs a verifier needs — **Verify, AI Chat, Log**. Home/student/admin tabs
are hidden and the portal opens straight on the Verify tab. The API surface
is unchanged (set `PUBLIC_MODE=1` separately if you also want admin
endpoints disabled). This is what a public-facing "verify end" should run
with.

The default boot is already private; this just makes it explicit and adds an
admin token:

```powershell
$env:PUBLIC_MODE="0"
$env:ADMIN_TOKEN="your-secret-token"     # optional; admin header is X-Admin-Token
uvicorn app.main:app --reload --no-proxy-headers
```

In private mode the **Issue / Revoke / Signers / API keys** tabs appear.

---

## 4. The six checks (what a verdict means)

Every verification runs these checks:

| # | Check | What it proves |
|---|-------|----------------|
| 1 | `chain_integrity` | The whole chain replays correctly — every block linked and valid |
| 2 | `signer_trusted` | The signer of the ISSUE block is on the trusted signer list |
| 3 | `on_chain_record` | An `ISSUE` block exists for this hash |
| 4 | `hash_match` | The uploaded document's hash equals the on-chain hash (needs the full document) |
| 5 | `signature_valid` | The ISSUE block's cryptographic signature verifies |
| 6 | `not_revoked` | No `REVOKE` block exists for this hash |

**Verdicts**

| Verdict | Meaning |
|---------|---------|
| `VALID ON CHAIN` | Checks 1–6 pass |
| `REVOKED` | The credential was issued, then revoked (with reason / effective date if recorded) |
| `NOT FOUND` | No ISSUE block for this hash |
| `INVALID` | Issued, but a check failed (e.g. untrusted signer, bad signature) |
| `CHAIN DATA CORRUPT` | The chain files are damaged — see Troubleshooting |

> A hash-only verification reports check 4 as `N/A` (the document is required);
> uploading the PDF/JSON runs all six.

---

## 5. Using the web UI

The UI is bilingual (中文优先 + English secondary). Since U25 there are two
single-purpose screens in front, and the old multi-tab console moved to
`/portal` — no route was removed, so every earlier instruction still works
there.

### 5.1 Verify — the landing page, `/`

One question, one input, one sentence:

1. Paste the verification code (the `HashedDocument` string) — or pick the
   certificate PDF/JSON. Both paths hit the same six checks; a PDF is hashed
   from its embedded document, a pasted hash is checked against the log.
2. Press **验证**. The card answers in plain language — **真的 / 已注销 /
   查不到 / 无法确认** — with one line explaining what that means.
3. **为什么？看六项检查** unfolds the six booleans in plain words (链条没被改过,
   签发方可信, 链上有这张证书, 文件跟编号对得上, 数字签名有效, 没有被注销).
4. **下载验证报告** appears only for a valid credential; the receipt ID is
   printed under the hash.

Deep links work: `/verify?hash=<hash>` prefills and verifies on load — that is
exactly what the QR code on the PDF points to.

Missing a certificate? The three chips at the bottom run the seeded VALID,
the revoked sample, and a fabricated hash, so the page can be demonstrated
without any files.

### 5.2 Issue — `/issue`

1. Fill three fields: **姓名**, **学号**, **学位 / 课程**. **补充信息** is
   optional (honour, issuer, issue date).
2. Press **签发并上链**. If this browser has no staff session, a **机构口令**
   box appears; the token is kept in `sessionStorage` for this browser only.
3. The result gives the block height, the verification code, **下载凭证 PDF**
   (the full copy with the embedded JSON), and **打开验证页看看**, which jumps
   to `/verify?hash=…` and shows VALID — the whole loop in one click.

### Verify tab (inside `/portal`)

1. **Drag & drop** a credential file onto the drop zone (or click to pick a
   file):
   - **PDF** → the portal **auto-fills** the credential JSON form via
     `POST /api/extract/pdf`: portal-issued PDFs are extracted byte-exact
     (green 「精确提取」note), text-layer certificates get label-aware field
     extraction (amber 「自动识别」note with confidence + low-confidence
     fields + warnings). The form opens automatically; review it, then click
     **验证 JSON 文档** — extraction never auto-submits a verdict.
   - **JSON / TXT** → verified immediately, no extra clicks.
2. Or **paste a credential hash** (`HashedDocument`) into the box and press
   **验证**.
3. Or click a sample chip — **真实有效 VALID** (the seeded diploma),
   **已注销 REVOKED** (public mode only), **查无此证 NOT FOUND** (a fabricated
   hash). Buttons that aren't available in the current mode are disabled with
   an explanation.
4. The verdict card shows a big plain-language banner
   （真实有效 VALID / 已注销 REVOKED / 查无此证 NOT FOUND / 无效 INVALID /
   链数据损坏), a holder summary (name / Student ID / degree / issuer) when a
   document was uploaded, the credential hash with a copy button, and actions:
   **下载验证报告** (receipt), **打印**, **生成 QR（放简历）**, **下载 PDF
   凭证**. The six checks are collapsed behind **查看 6 项安全检查** for people
   who want the detail.
5. The receipt (HTML, printable) contains the hash, six checks, revocation
   status, verification timestamp, verifier version + chain snapshot, a
   receipt ID (`RCP-…`), and the disclaimer:

   > "真实有效 表示在此时刻 6 项检查均通过；本报告不构成法律认证。"
   > (VALID means the six checks passed against the log at this timestamp;
   > it is not a legal certification.)

   It deliberately contains **no DOB and a masked StudentID**.

6. **Batch verify** (employers): paste up to 500 hashes, one per line →
   summary + per-row results with receipt IDs → **下载结果 CSV**.

### Student tab

A holder opens the link the school gave them (`/me/<token>`). `StudentID + DOB`
is no longer accepted (U12 R3: that pair was an enumerable privacy gate). The
page shows the issue point (block + time), a verification QR, **下载凭证 PDF**,
and the revocation reason if the credential was revoked. When the link has
under seven days left it grows **续期这个链接** (U14): that re-signs the same
credential for another 30 days, so a holder whose employer still holds the
old link does not have to ask the office for a new one. Old links keep working
until their own expiry, so renewing never breaks a link already shared.

### Registrar tab (admin)

Signing in at `/staff/login` gives a 30-minute console session. Each role
keeps at most three live sessions (the fourth sign-in evicts the oldest),
**退出所有设备** clears every session of your role server-side, and five wrong
tokens from one address inside ten minutes lock the form (U14).
- **批量签发毕业证 (Batch-issue wizard)** — the fastest way to issue a cohort:
  1. **下载 CSV 模板** for the exact column format (Chinese/English header
     aliases are accepted, e.g. `surname/姓`, `student_id/学号`, `degree/学位`,
     `email/邮箱`).
  2. Upload the CSV or paste it into the box; an optional 签发机构 field fills
     the issuer for rows without one.
  3. A live **预览** shows valid rows vs. problem rows (missing name, duplicate)
     with reasons, and the button becomes **签发 N 份 Issue**.
  4. One click issues everything via `POST /api/issue/batch` — each row is
     independent, so a bad row never rolls back the good ones. The results
     table gives per-row 凭证编号 + PDF / QR download links, a **持证人链接**
     button (copies the `/me/<token>` URL) and **导出全部持证人链接 CSV**
     (U13 F5).
- **单个签发 (Issue one)** — paste a credential JSON, optionally a student
  email → hash, height, verifiable PDF, QR, notification (dry-run by default).
- **公开 API 密钥** — create per-integration keys for the batch/API flow
  (§8).

### Revoke tab (admin)

Enter a hash, optionally add a **reason** and **effective date (unix
seconds)**. The verdict and receipt surface both.

### Self-issue tab (自制, admin)

No real PDF handy? Fill in your own details and the portal **acts as the
issuing side**:

1. Fill the form (surname / given names / student ID / degree are required;
   a Chinese name works — the PDF renderer embeds CJK fonts).
2. Click **生成并签发上链 Build + Issue** — the credential is built,
   signed and appended to the chain **and** a verifiable PDF + JSON are
   saved into the main project folder (`自制凭证-outputs/`).
3. Anyone can now upload that PDF (or follow **立即验证此凭证**) and get a
   **真实有效 VALID** verdict — the full issue→share→verify loop with your
   own data.
4. **仅生成草稿（不上链）** produces the same files *without* chain
   issuance (uploading them verifies as 查无此证 until an admin issues).

The generated files are listed at the bottom of the tab with download links.
This is an issue-side action, so it is hidden in public verifier mode
(`PUBLIC_MODE=1`) and gated by the same admin rule as `POST /api/issue`.

### Signers tab (admin)

Manage trusted signer keys: list, add (algorithm: `ML_DSA_65`,
`RSA_PSS_2048`, `ec.secp256r1`), activate one, see fingerprints.

Old keys can be **retired** instead of deleted. Retirement records a height
boundary (`retired_at_height`), so blocks the key signed before that height still
verify while anything after it does not — the key stays in the registry, and the
badge reads *退役于块 #N*. The active signer cannot be retired (switch first, or
its next block would be signed by an untrusted key and the whole chain would read
`INVALID`); a retired key cannot be made active again. Re-registering the same
public key clears the boundary.

### AI Chat tab

Ask natural-language questions, e.g.:

- *"Has CHAN TAI MAN's diploma been revoked?"*
- *"What degree did student 22000000 earn?"*
- *"Show me the transcript of NG KA LOK."*
- *"Who signed this credential?"*

The assistant answers from the chain + raw documents (RAG), and cites the
source blocks. **Person-in-context:** when it resolves a person, it shows a
profile card (StudentID masked, **no DOB**). Follow-ups like *"and him?"*
work within a session.

**Web research:** the assistant can go online to look up the person in
context. Controlled by:

- `WEB_RESEARCH_ENABLED=1` (default) — web search on by default
- `WEB_RESEARCH_MOCK=1` — no network needed; returns clearly-labeled
  **DEMO DATA** results (use this in offline sandboxes)

### Log tab

- **公开验证日志 Verifications** — anonymized public log of recent
  verifications (hash prefixes only; builds trust)
- **链尾 Chain tail** — last blocks with action / height
- **异常监控 Anomaly watch** — IsolationForest + rule-based flagging of bursty
  issuing (e.g. > 20 issues/hour triggers a flag) + a 24-hour histogram
- **通知记录 Notifications** — recent notifier events

---

## 6. Institute-issued PDFs

- **Portal-issued PDFs (Path A)** are fully supported: the credential JSON is
  embedded in the PDF; uploading it to **Verify** extracts the JSON and runs
  the exact six checks. Since U13 the full file has two staff/holder-only
  routes — `GET /api/admin/pdf/{hash}` (staff) and `GET /api/me/{cap}/pdf`
  (the holder's signed link) — while `GET /api/pdf/{hash}` now returns a
  **verification report** with the identity fields withheld and no embedded
  JSON, so a public hash is not a bearer credential.
- **Foreign / scanned PDFs (OCR soft-check, Path B)** — the round-4 OCR
  soft-check module (`app/pdf_softcheck.py` + `/api/verify/soft`) is **not
  included in this local copy** (it was never part of the packaged zip).
  Everything else is present. Add it from the cloud build if you need
  OCR-based visual matching of non-portal PDFs.

---

## 7. API reference (with examples)

Base URL: `http://127.0.0.1:8000` (or your deployed URL).

| Method & path | Purpose | Auth |
|---|---|---|
| `GET /healthz` | liveness | — |
| `GET /api/version` | app version, public mode, chain height, status-list digest | — |
| `GET /api/diagnostics` | the text behind `/healthz`'s counts: config messages, chain integrity, signers + `retired_at_height`, uptime (U19) | admin |
| `POST /api/issue` `{"document": {...}, "student_email": "..."}` | issue a credential | admin |
| `POST /api/issue/batch` `{"credentials": [{"document", "student_email"?}]}` | batch issue (≤ `BATCH_ISSUE_MAX`, default 200) — per-row results, bad rows never block good rows | admin |
| `POST /api/revoke` `{"hashed_document": "...", "reason": "...", "effective_at": 1700000000}` | revoke; `effective_at` is recorded metadata and a future value is rejected `422` (revocation is immediate, so don't pretend otherwise) | admin |
| `GET /api/verify/{hash}` | six checks by hash | — / API key |
| `POST /api/verify/document` (JSON or multipart file) | six checks with hash_match | — / API key |
| `POST /api/extract/pdf` (multipart PDF) | PDF auto-fill: `{mode, confidence, document, field_confidence, warnings}` — JSON draft for the form, never a verdict | — / API key |
| `POST /api/verify/batch` `{"hashes": ["..."]}` | batch verify ≤ 500 hashes | — / API key |
| `GET /api/status/{hash}` | raw on-chain lifecycle (503 if chain corrupt) | — |
| `GET /api/statuslist` | signed revocation status list (ETag-cached); v2 signature includes the nonce and the signing key's fingerprint | — |
| `GET /api/signers/keys` | public keys (PEM) + fingerprints + retirement boundaries — offline trust anchor | — |
| `GET /api/receipt/{receipt_id}` | look up a stored receipt | — |
| `GET /api/qr/{hash}` | PNG QR → verify page | — |
| `GET /api/log` | anonymized verification log + chain tail | — |
| `GET /api/anomalies` | hourly issue counts + anomaly flags | — |
| `GET /api/notifications` | recent notifier events | admin (U13 F2) |
| `GET /api/me/{cap}` | the one credential behind a holder link (404 for forged/expired) | — (signature in the link) |
| `POST /api/chat` `{"question": "...", "session_id": "...", "web": true}` | RAG assistant | — |
| `GET /api/rag/status` | embedder / index state | — |
| `POST /api/signers`, `POST /api/signers/active`, `POST /api/signers/retire`, `GET /api/signers` | signer registry / active switch / retire a key's trust from a height on | admin |
| `GET/POST /api/admin/apikeys`, `DELETE /api/admin/apikeys/{kid}` | API-key lifecycle | admin |
| `POST /api/custom/build` `{surname, given_names, student_id, degree, ..., issue: true}` | self-service credential maker: build → **issue on chain** → render verifiable PDF + JSON, saved to the main project `自制凭证-outputs/`; `issue:false` = draft (not on chain) | admin |
| `GET /api/custom/list` | generated self-service files, newest first | admin |
| `GET /api/custom/file/{file_id}/{kind}` | download a generated PDF (`kind=pdf`) or JSON (`kind=json`) | admin |
| `GET /api/demo/credentials` | sample credentials (diploma / transcript / revoked_sample) | — |
| `GET /api/pdf/{hash}` · `GET /api/admin/pdf/{hash}` · `GET /api/me/{cap}/pdf` | three PDF forms: public **verification report** (identity withheld, no attachment) · staff **full credential** · holder full credential through a signed link. A revoked hash gets a red **REVOKED ON CHAIN** band (U14); a broken chain gets a red **CHAIN INTEGRITY FAILED** line and a footer pushed down (U19). Each page carries a QR, and prints `Verify online: <url>` if the QR cannot be drawn. Fields too long for the card are truncated with a note (the embedded JSON always has them in full) so the QR and red bands stay on the page (U21). Single-line text is fitted by measured width with `...` — a long institution name or a 44-character CJK name no longer runs off the right edge (U22) | admin (last two) |
| `POST /api/me/{cap}/renew` | holder self-renewal: allowed only in the last 7 days of the link, returns a fresh 30-day link (U14) | — (signature in the link) |
| `POST /staff/logout/all` | drop every live console session of the caller's role (U14) | staff session |

**Examples**

```bash
# Verify by hash
curl http://127.0.0.1:8000/api/verify/GFiY4d67yoi8X4wmwnL_8IX18_xo_F7HOQgWBdHZXubNTLhvVX_K1PCWuKZa8cntDWyq5Mnr7i8yvAopAjxrGQ

# Verify by document
curl -X POST http://127.0.0.1:8000/api/verify/document \
  -H "Content-Type: application/json" \
  -d '{"document": {"PersonalParticulars": {...}, "AcademicInfo": {...}, "DocumentInfo": {...}}}'

# Batch verify
curl -X POST http://127.0.0.1:8000/api/verify/batch \
  -H "Content-Type: application/json" \
  -d '{"hashes": ["<hash1>", "<hash2>"]}'

# AI chat with web research
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Has CHAN TAI MAN\x27s diploma been revoked?", "web": true}'
```

**API keys.** In private mode, create a key via the UI (or
`POST /api/admin/apikeys` with the admin header), then send
`Authorization: Bearer <key>` on verify/batch endpoints. Keys raise the
rate limit to `API_KEY_MAX` (600/min); revoked keys get `401`.

**Limits & guards** (built into the API): uploads ≤ 5 MB, JSON body ≤ 6 MB,
document JSON ≤ 2 MB, nesting ≤ 50 levels, batch ≤ 500 rows, public rate
limit 120/min, admin 30/min.

---

## 8. Employer pack (CLI)

```powershell
# Input CSV must have a column named hashed_document (or hash)
python scripts\batch_verify.py --csv candidates.csv --out results.csv --api http://127.0.0.1:8000
# Optional: --api-key <key>
```

The output CSV passes through your original columns and adds:
`verdict`, the six checks, `receipt_id`, `reason`, `effective_at`, and a
`SUMMARY` row (total / valid / revoked / not found / invalid / error).
Exit code 0 = the API is reachable and the run completed.

### Offline revocation checking

Save the two responses once, then check them with no network:

```powershell
curl.exe -o statuslist.json http://127.0.0.1:8000/api/statuslist
curl.exe -o anchors.json   http://127.0.0.1:8000/api/signers/keys
python scripts\verify_statuslist.py statuslist.json anchors.json
python scripts\verify_statuslist.py statuslist.json anchors.json --hash <credential-hash>
# anchor it: require the key you already know, and lock the set on first use
python scripts\verify_statuslist.py statuslist.json anchors.json `
  --expect f2:6d:75:a5:22:38:e9:b4:5f:a6:4f:b4:1b:13:da:d9 --pin trust-anchor.pin.json
```

Exit code 0 = the signature verifies against a published key. A tampered row, a
missing anchor entry, a key whose PEM does not match its fingerprint, a list
signed by a key *after* its `retired_at_height`, an anchor that does not match
the pin, or an unreadable pin file all exit 1 with a reason. Only a verified
list is allowed to answer "not revoked" — an unverified list proves nothing about
absence.

A signature alone only shows the list and the anchor agree with each other; if
both came from the same hijacked source, a fake list signed with attacker keys
would pass. `--expect` is the hard guarantee (state the fingerprint you obtained
out of band, e.g. from the university's published page); `--pin` is the
convenient trust-on-first-use variant. A **broken** pin fails closed and is
never treated as first use; a **deleted** pin does look like first use, so keep
it somewhere you control (a read-only file, a CI variable, a printed record).

After a legitimate key rotation, do not delete the pin. Record the rotation:

```powershell
python scripts\verify_statuslist.py statuslist.json anchors.json `
  --pin trust-anchor.pin.json --pin-update `
  --expect f2:6d:75:...          # the new fingerprint, confirmed out of band
```

`--pin-update` rewrites the pin only if the list itself verifies, then appends
the old set, the new set and a UTC timestamp to the pin's `history` (schema
`gef26.trust-anchor.pin.v2`; a v1 pin is still readable and upgrades on its next
update). Without `--expect` the output carries a warning: the new key would be
vouched for only by the same channel that delivered it.

---

## 9. Persistence & backup

The chain lives in `CHAIN_DIR` (default `data/demo-chain`). Back it up:

```powershell
# export a snapshot (tar.gz, path-traversal-safe)
python scripts\backup_chain.py export --dir data\demo-chain --out data\chain-backup.tar.gz

# import / restore (refuses to overwrite an existing chain)
python scripts\backup_chain.py import --dir data\restored-chain --in data\chain-backup.tar.gz
```

**Restart persistence.** On boot, the portal auto-restores from
`CHAIN_SNAPSHOT_URL` if the chain dir is empty, then seeds samples if still
empty. Proven by `tests/test_restart_persistence.py` (real uvicorn subprocess,
2/2 green). See `docs/DEPLOY.md` for the free-tier vs paid-disk decision.

---

## 10. Running the tests

```powershell
# Full suite, module-by-module (each module isolates its own state):
python scripts\run_all_tests.py        # 10/10 modules green, 94 tests

# Or run modules individually:
python -m unittest tests.test_api -v
python -m unittest tests.test_issue_batch -v
python -m unittest tests.test_employer_pack tests.test_public_mode -v
```

**Smoke test** (in-process, no server needed):

```powershell
python scripts\local_smoke.py public    # public verifier checks (26)
python scripts\local_smoke.py private   # admin issue/revoke + API-key lifecycle
```

---

## 11. Configuration reference

Set via environment variables (see `app/config.py` for defaults).

| Env var | Default | Meaning |
|---|---|---|
| `PUBLIC_MODE` | `0` | `1` → verifier-only (admin 403, admin UI hidden); `0` → admin available |
| `ADMIN_TOKEN` | (none) | If set, admin endpoints require `X-Admin-Token: <token>` |
| `CHAIN_DIR` | `data/demo-chain` | Where the chain + raw docs live |
| `CHAIN_SNAPSHOT_URL` | (none) | Boot-time restore source when chain dir is empty |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | Base URL used in QR codes / receipts |
| `APP_VERSION` | `6.0.0` | Version shown in `/api/version` + receipts |
| `MAX_UPLOAD_BYTES` / `MAX_JSON_BYTES` / `MAX_BODY_BYTES` / `MAX_JSON_DEPTH` | 5 MB / 2 MB / 6 MB / 50 | input guards |
| `RATE_LIMIT_PUBLIC_MAX` / `RATE_LIMIT_ADMIN_MAX` | 120 / 30 | per-minute limits |
| `API_KEY_MAX` | 600 | per-minute limit for valid API keys |
| `RECEIPT_REGISTRY_CAP` / `STATUSLIST_MAX_ENTRIES` | 5000 / 20000 | caps |
| `BATCH_ISSUE_MAX` | 200 | max rows per `POST /api/issue/batch` |
| `SIGNER_NAME` / `SIGNER_ALGO` | UNIVERSITY OF UTOPIA / ML_DSA_65 | default signer |
| `ANOMALY_ISSUE_PER_HOUR` | 20 | anomaly threshold |
| `EMAIL_ENABLED` / `SMTP_*` | off | email notifier (dry-run when off) |
| `WEB_RESEARCH_ENABLED` / `WEB_RESEARCH_MOCK` | 1 / 0 | AI web research toggle + mock mode |
| `SOFT_OCR` | 1 | reserved for the OCR soft-check module (not in this copy) |

---

## 12. Deploying

Follow `docs/DEPLOY.md`: push to GitHub → Render Blueprint (or Railway) →
set `PUBLIC_MODE=1` → attach a disk (paid) or set `CHAIN_SNAPSHOT_URL`
(free) → run the restart-persistence drill. **Never put the admin panel with
a static token on the public internet** before real auth.

---

## 13. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `CHAIN DATA CORRUPT` verdict | A block file is damaged. Restore from a backup (`backup_chain.py import`) or delete `CHAIN_DIR` to re-seed samples. |
| `/api/qr` returns 503 | `qrcode` not installed → `pip install qrcode`. |
| Chat is low-quality | `sentence-transformers` + `faiss-cpu` missing → the fallback hashing embedder is used (still answers, lower retrieval quality). Install requirements. |
| Web card shows DEMO DATA | `WEB_RESEARCH_MOCK=1` — set to `0` for real network search. |
| `403` on issue/revoke | You're in public mode — run `PUBLIC_MODE=0` with `ADMIN_TOKEN`. |
| `401 Invalid or revoked API key` | Key was revoked or mistyped; create a new one in the API-keys card. |
| Receipt lookup 404 | Receipts are a bounded registry (cap 5000); old ones are evicted. |
| Verified credential gone after restart | Ephemeral storage — mount a disk or set `CHAIN_SNAPSHOT_URL`. |
| Upload rejected 413 / 422 | Size or depth guards — see §7 limits. |

---

## 14. Project layout (key files)

```
app/
├── main.py              # FastAPI app: all endpoints, rate limiting, admin guard
├── chain_service.py     # verify/issue/revoke/snapshot logic over blockchain_util
├── blockchain_util.py   # chain format, blocks, signers, ML-DSA/RSA/ECDSA signing
├── crypto_util.py       # hashing, JSON canonicalization (JCS), key mgmt
├── chat_service.py      # RAG chat orchestration
├── rag_embedder.py / rag_indexer.py / rag_generator.py
├── person_context.py    # person resolution + profile (masked) + web research
├── web_research.py      # optional web lookup for the AI
├── pdf_diploma.py       # portal-issued verifiable PDF (embedded JSON)
├── anomaly.py           # IsolationForest + rule-based issue anomaly flags
├── public_log.py        # anonymized verification log (persistent)
├── apikeys.py           # API-key store (hashed)
├── receipt_registry.py  # bounded receipt store
├── statuslist.py        # signed revocation status list + ETag
├── notifier.py          # email notifier (dry-run default)
├── rate_limit.py        # token-bucket limiter
├── config.py            # all env-driven configuration
└── schemas.py           # Pydantic request models
static/index.html        # bilingual, role-based single-page UI (round 8 UX)
scripts/
├── batch_verify.py      # employer-pack CLI
├── backup_chain.py      # export/import chain snapshots
├── run_all_tests.py     # per-module test runner (10 modules)
├── local_smoke.py       # 2-phase in-process smoke
└── build_demo_video.py  # demo video generator
start_portal.bat / start_portal.sh   # one-click launchers
```

---

## 15. Honest boundaries

- **Verification is exact, not semantic.** A printed/scanned diploma cannot be
  OCR'd back into the exact JSON this chain hashes — which is why portal
  PDFs embed the JSON. Foreign PDFs get a clear error asking for the hash or
  the JSON upload (Path B soft-check is not in this local copy).
- **VALID is not a legal certification** — every receipt says so.
- **Public mode is verifier-only by design**; admin needs real auth before
  production exposure.
- The RAG web research depends on network availability; mock mode is for
  offline demos.

## 16. Showcase day (现场演示)

Two days' worth of preparation collapses into one double-click:

```powershell
.\start_showcase.bat
```

It frees port 8013, opens a Cloudflare quick tunnel (retrying when the quick
tunnel quota answers `429`), starts the portal with `PUBLIC_BASE_URL` set to
that public address and `TRUSTED_PROXIES=127.0.0.1`, waits for `/healthz`,
prints the URL, writes it to `showcase-url.txt`, and opens the stage screen.

What the audience sees:

1. `/showtime` — press **开始**: issue a credential (block N), verify it
   (✅ 真的), revoke it (block M), verify again (↩ 已注销). Every step is a
   real API call; the whole run is about 12 seconds.
2. The QR on that screen points at `PUBLIC_BASE_URL/verify?hash=…`, so anyone
   can scan it on their own phone and land on the same verdict. Visitors can
   verify; they cannot issue (that needs the staff token, by design).

Things to know before the doors open:

- **The tunnel URL changes on every restart.** Print it on a slide or a
  sticky note, never on the poster.
- **Keep the laptop awake.** Closing the lid kills the tunnel and the portal.
- **Have a fallback.** If the network dies, drive the same four steps from
  `http://127.0.0.1:8013/showtime` on the projector; the stage works fully
  offline, only the QR stops being scannable.
- Team token card (if you want judges to issue too): `demo-staff-token`
  entered in the `/issue` page, or `?token=…` on `/showtime` once.
