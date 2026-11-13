# GitHub Push Guide — GEF Mobile

Local git is already initialized and committed. Only the remote creation and
push need your GitHub account.

## What is already done locally

- Repo root: this folder (`GEF-mobile-project/`), branch `main`.
- Initial commit: `8356e80` — 85 files, source code, tests, docs, demo video
  and poster.
- Ignored (never committed): `.venv/`, `verification-portal/data/` (chain state
  and demo private keys), `__pycache__/`, video intermediates
  (`narration.wav`, `clip*.mp4`, `concat.*`, `shots/`).

## Steps

1. On GitHub, click **New repository**:
   - Name: e.g. `gef-mobile-credential-portal`
   - Visibility: **Public** (the summary needs a shareable source-code link;
     choose Private only if the course allows it).
   - **Do NOT** tick "Add a README", `.gitignore` or license — the repo must be
     empty, otherwise the first push conflicts.
   - Create repository.

2. In this folder, point the local repo at the new GitHub repo and push
   (replace `<your-username>` and `<repo-name>`):

   ```bash
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git branch -M main
   git push -u origin main
   ```

   The first push opens a GitHub sign-in / credential prompt; sign in with your
   account (browser or personal access token).

3. Copy the repository URL, e.g.
   `https://github.com/<your-username>/<repo-name>`, and paste it into
   `Learning_Summary_draft.md` under **Source code (GitHub)**.

## After pushing, verify

- The remote file list must **not** contain `.venv/`, `data/`, `keys/`,
  `narration.wav` or `shots/`.
- Repo size should be a few MB (two demo MP4s are the only large binaries).

## Notes

- The local commit author is a placeholder (`GEF Mobile Team`, noreply email).
  To use your own identity before pushing:

  ```bash
  git config user.name "Your Name"
  git config user.email "you@example.com"
  git commit --amend --no-edit --author="Your Name <you@example.com>"
  ```

- If you made changes after the commit, stage and commit them again:
  `git add -A && git commit -m "..."` before pushing.
