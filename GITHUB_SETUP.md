# GitHub — pushed

Status: **done**. The repository is public and in sync with this folder.

- Remote: `https://github.com/JohnnyYau/gef-mobile-credential-portal`
- Branch: `main`, tracking `origin/main`
- Latest commit when this was written: `ad8643f` (U25/U26 — one-screen
  verification, issue page, showtime stage, tunnel + same-origin fix)

## What is not published

Ignored by `.gitignore`, never committed:

- `.venv/` (104 MB, rebuilt from `requirements.txt`)
- `verification-portal/data/` — chain state, demo private keys, raw index
- `verification-portal/showcase-url.txt`, build zips (`*.zip`), `rag-cache/`
- demo video intermediates (`narration.wav`, `clip*.mp4`, `concat.*`, `shots/`)

The chain re-seeds itself with demo keys on first start, so a fresh clone runs
without any of those files.

## If you ever need to re-point the remote

```bash
git remote set-url origin https://github.com/<user>/<repo>.git
git push -u origin main
```

## Remaining manual step

`P14_Learning_Summary.docx` still embeds the GitHub link as plain text — the
docx was written before the repo existed. Re-generate it from
`Learning_Summary_draft.md` (which now carries the real URL) before uploading.
