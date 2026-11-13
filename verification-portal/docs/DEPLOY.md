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

## 2. Render

1. `git init && git add -A && git commit` in the project root, push to GitHub.
2. Render → **New → Blueprint**, select the repo. `render.yaml` defines the
   web service (Python 3.12, `uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
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
`tests/test_restart_persistence.py` (2/2 green locally).

## 5. Security note

The web service is meant to run in **public verifier mode** (`PUBLIC_MODE=1`):
admin endpoints return 403 and the admin UI is hidden. Issue/revoke live
behind `ADMIN_TOKEN` — keep the private instance off the public internet
until real auth (sessions/2FA/RBAC) is in place.
