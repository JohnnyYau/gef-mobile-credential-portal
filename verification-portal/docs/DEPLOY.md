# Deployment: Render / Railway / Fly.io

This app is a plain FastAPI service — it deploys to any container host. The
`render.yaml` and `railway.toml` blueprints in the repo root configure it.

## 1. Before you deploy — the persistence decision

The chain and its supporting data live in `CHAIN_DIR` (default
`data/demo-chain` under the app dir). Two options:

- **Paid tier with a disk (recommended):** mount a persistent volume and set
  `CHAIN_DIR=/data/demo-chain`. A restart keeps every credential and the log.
- **Free tier (ephemeral storage):** the filesystem resets on every restart.
  The blueprint ships with two mitigations:
  1. The portal **auto-seeds** a fresh demo chain on first boot (sample
     VALID / REVOKED / INVALID credentials are always available).
  2. `CHAIN_SNAPSHOT_URL` — point it at a hosted snapshot of `chain-backup.tar.gz`
     (e.g. a Gist/R2/S3 URL). On boot, if `CHAIN_DIR` is empty, the portal
     downloads and restores the snapshot before seeding.

> Free-tier caveat: if a user issues a credential and the instance restarts,
> that credential is lost unless the chain was snapshotted. For a real pilot,
> use a paid tier with a disk.

### 1.1 Volumes and what must live on them

Everything the portal cannot regenerate belongs under `CHAIN_DIR`:

| Path | Content | Lost on ephemeral storage? |
| --- | --- | --- |
| `$CHAIN_DIR/blocks/` | the ledger itself | yes — every credential gone |
| `$CHAIN_DIR/info.yaml` | chain identity, trusted signers | yes |
| `$CHAIN_DIR/keys/` | signer keys (private + public) | yes — restored chain cannot issue without them |
| `$CHAIN_DIR/rawjsondocs/` | stored credentials (PDF lookup, RAG, disclosure) — **plaintext identity data** | yes |
| `$CHAIN_DIR/holder_index/` | one PII-free row per credential (StudentID, hash, type, degree); what the holder link reads | yes (rebuildable from `rawjsondocs/`, or from reissue) |
| `$SQLITE_PATH` (`data/portal.sqlite3`) | receipts, log, audit, API keys, revocation index (when `STORAGE_BACKEND=sqlite`) | yes |

Mount **one** volume and point both at it: `CHAIN_DIR=/data/demo-chain`,
`SQLITE_PATH=/data/portal.sqlite3`. Mounting only `CHAIN_DIR` and leaving the
SQLite file on the container filesystem gives a half-persistent portal: the
credentials survive a restart but the receipts / audit trail / API keys do not.

### 1.1b The public instance must not have `rawjsondocs/` (U12 R5)

`rawjsondocs/` is the only place in the tree where a credential's name, DOB and
e-mail exist in plaintext. Split by role rather than by flag:

| Instance | `rawjsondocs/` | `holder_index/` | Why |
| --- | --- | --- | --- |
| issuer (private) | yes | yes | needs full documents for PDF, disclosure and RAG |
| public / verifier | **no** | yes (copy) | holders still open their own link; nothing else needs plaintext |

Holder links read `holder_index/`, never `rawjsondocs/`, so a public instance
with the index copied over serves `/me/<cap>` and `/api/me/<cap>` while having
no plaintext identity data on disk. Verification itself never needed either
directory — it reads the chain.

The submission bundle follows the same rule: `build_package.py` drops `data/`
entirely and then scans the finished zip, failing the build if any entry is a
`rawjsondocs` path, a `.pem`/`.env` file, or contains a `"DOB"` / `"Email"` /
`"Name"` / `"MobileNo"` / `"Sex"` key. A fresh clone therefore starts by
generating its own signer keys and seeding its own demo chain.


### 1.2 Snapshot format (U8.1)

`scripts/backup_chain.py export` writes a tar.gz that now carries
`MANIFEST.json`: chain name, height, whether private keys are included, and a
SHA-256 per file. Verify and restore before trusting a snapshot:

```bash
python scripts/backup_chain.py export --dir /data/demo-chain --out /data/snap.tar.gz
python scripts/backup_chain.py verify --in /data/snap.tar.gz      # members + checksums
python scripts/backup_chain.py import --dir /data/restored --in /data/snap.tar.gz
python scripts/restore_drill.py --dir /data/demo-chain            # full rehearsal
```

Boot-time restore from `CHAIN_SNAPSHOT_URL` performs the same checks: unsafe
members (absolute paths, `..`, symlinks, hardlinks, devices) abort, and a
manifest mismatch aborts the boot — a chain that cannot prove itself is worse
than an empty one that re-seeds.

## 2. Render

1. `git init && git add -A && git commit` in the project root, push to GitHub.
2. Render → **New → Blueprint**, select the repo. `render.yaml` defines the
   web service (Python 3.12, `uvicorn app.main:app --host 0.0.0.0 --port $PORT
   --no-proxy-headers`).
3. Env vars in the blueprint: `PUBLIC_MODE=1`, `ADMIN_TOKEN=<a long random
   string>`, `PUBLIC_BASE_URL=<your https URL>`.
4. **Paid tier:** uncomment the `disk` block in `render.yaml`, set
   `mountPath: /data`, and set `CHAIN_DIR=/data/demo-chain`.
5. Deploy. Open the URL — you should see the verifier UI with the amber
   "public verifier mode" banner and three sample buttons.

## 3. Railway

`railway.toml` sets the start command. Same env vars. For persistence on
Railway, add a **Volume** mounted at `/data` and set `CHAIN_DIR=/data/demo-chain`.

## 4. Restart-persistence drill (do this after deploying)

1. Open the deployed URL, issue a credential (private instance) or verify a
   sample (public instance).
2. Trigger a manual redeploy/restart in the dashboard.
3. Re-open the URL and verify the same credential.
4. If it says `NOT FOUND`, persistence is broken — fix the disk mount or
   `CHAIN_SNAPSHOT_URL` before inviting anyone.

The automated equivalent of this drill lives in
`tests/test_restart_persistence.py` (2/2 green locally); the backup/restore
drill is `scripts/restore_drill.py` (6 steps, exit 0 only if every step passes).

## 5. Security note

The web service is meant to run in **public verifier mode** (`PUBLIC_MODE=1`):
admin endpoints return 403 and the admin UI is hidden. Issue/revoke live
behind `ADMIN_TOKEN` — keep the private instance off the public internet
until real auth (sessions/2FA/RBAC) is in place.

**Signer key at rest (batch U10).** A private instance writes its issuer key to
`<CHAIN_DIR>/keys/signer-*.priv.pem`. Unencrypted by default (the demo's
historical behaviour). For anything beyond a local demo set
`GEF_KEY_PASSPHRASE=<a long random string>` in the deployment's secret store:

- keys generated after that are written encrypted (PKCS#8 PBES2, scrypt +
  AES-256 via `cryptography`);
- an existing plaintext key is re-encrypted in place on first load — back up
  the chain dir before the first boot if the old file matters;
- a passphrase that does not match the key on disk stops issuing with a typed
  error (`SignerUnavailableError`, 503 at the endpoint). The app never
  generates a replacement key, because every block already signed would then
  fail its signature check;
- `/healthz` reports `checks.config.warnings` when keys are unencrypted or a
  passphrase is set but the key file has not been migrated yet.
