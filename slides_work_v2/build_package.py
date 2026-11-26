"""Build the P14 submission bundle.

Collects only what a grader or a teammate needs to run and read the project,
and deliberately leaves out the virtualenv, tool caches, logs and pid files.
"""
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # ...\GEF-mobile-project
PORTAL = ROOT / "verification-portal"
OUT = ROOT / "P14-Mobile-Credential-Verification-Portal.zip"
ARC_ROOT = "P14-Mobile-Credential-Verification-Portal"

EXCLUDE_DIRS = {
    ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".hypothesis", ".git", "rag-cache",
    # U12 R5: plaintext credential documents (names, DOB, e-mail) must never
    # travel inside a submission bundle, and neither must the demo private
    # keys. Both live under data/. Dropping data/ whole means the bundle boots
    # into a freshly seeded chain with freshly generated keys instead of
    # shipping someone else's (see ensure_chain).
    "data",
    "rawjsondocs",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".pid", ".tmp", ".npz.tmp"}
EXCLUDE_NAMES = {
    "portal_live.pid", "portal_test.pid", ".DS_Store", "Thumbs.db",
    # Runtime state produced by a local demo run; rebuilt on first start.
    "apikeys.json", "receipts.json", "revocation-index.json",
    "audit-log.jsonl", "notifications.jsonl", "portal.sqlite3",
}

# PII markers that must not appear in any JSON inside the bundle.
PII_KEYS = (b'"DOB"', b'"Email"', b'"Name"', b'"MobileNo"', b'"Sex"')

# Explicit extras that sit outside verification-portal/
EXTRAS = [
    "P14_Learning_Summary.docx",
    "P14-A0-Poster.pptx",
    "P14-A0-Poster.pdf",
    "P14-Showcase-Deck.pptx",
    "P14-Run-Sheet.pdf",
    "P14-A0-Poster-preview.png",
    "USAGE.md",
    "CODE_WALKTHROUGH.md",
    "demo-media",
    "模拟凭证-烧鸡.pdf",
]

# demo-media/ is the video build workspace; ship only what a reader needs.
DEMO_MEDIA_KEEP = {
    "GEF-mobile-demo.mp4",
    "GEF-mobile-stage-run.mp4",
    "GEF-mobile-walkthrough.mp4",
    "poster-海报.png",
    "poster-海报-v2.png",
}


def wanted(path: Path) -> bool:
    if path.name in EXCLUDE_NAMES:
        return False
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    if path.name.startswith("~$"):
        return False
    return True


def add_tree(zf: zipfile.ZipFile, base: Path, arc_prefix: str, manifest: list):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in sorted(filenames):
            src = Path(dirpath) / name
            if not wanted(src):
                continue
            arc = f"{arc_prefix}/{src.relative_to(base).as_posix()}"
            zf.write(src, arc)
            manifest.append((arc, src.stat().st_size))


def verify_bundle(path: Path) -> int:
    """Fail loudly if the bundle carries plaintext identity data.

    Checked on the finished archive rather than on the source tree: the
    question is what a recipient receives, not what the builder meant to skip.
    """
    problems = []
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        for name in names:
            low = name.lower()
            if "rawjsondocs" in low:
                problems.append(f"rawjsondocs entry: {name}")
            if low.endswith((".env", ".pem", ".key")) or low.endswith("/.env"):
                problems.append(f"secret-looking entry: {name}")
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                raw = zf.read(name)
            except Exception:
                continue
            hits = [k.decode() for k in PII_KEYS if k in raw]
            if hits:
                problems.append(f"PII {hits} in {name}")
    if problems:
        print("\nBUNDLE CHECK FAILED")
        for p in problems[:20]:
            print("  " + p)
        if len(problems) > 20:
            print(f"  ... {len(problems) - 20} more")
        return 1
    print("bundle check: no rawjsondocs, no PII keys, no secret-looking files")
    return 0


def main():
    if OUT.exists():
        OUT.unlink()
    manifest: list = []
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        add_tree(zf, PORTAL, f"{ARC_ROOT}/verification-portal", manifest)
        for extra in EXTRAS:
            src = ROOT / extra
            if not src.exists():
                print(f"  [skip missing] {extra}")
                continue
            if src.is_dir():
                if extra == "demo-media":
                    for name in sorted(DEMO_MEDIA_KEEP):
                        f = src / name
                        if not f.exists():
                            continue
                        arc = f"{ARC_ROOT}/demo-media/{name}"
                        zf.write(f, arc)
                        manifest.append((arc, f.stat().st_size))
                else:
                    add_tree(zf, src, f"{ARC_ROOT}/{extra}", manifest)
            else:
                arc = f"{ARC_ROOT}/{extra}"
                zf.write(src, arc)
                manifest.append((arc, src.stat().st_size))

        contents = [
            "P14 - Mobile Credential Verification Portal",
            "Submission bundle",
            "",
            "Layout",
            "  verification-portal/   running system (FastAPI + static UI, tests, docs)",
            "  P14_Learning_Summary.docx   the Learning Summary submission",
            "  demo-media/            demo video and poster images",
            "  USAGE.md, CODE_WALKTHROUGH.md   usage guide and per-module walkthrough",
            "",
            "Run it",
            "  Windows : double-click verification-portal/start_portal_admin.bat",
            "  macOS/Linux : bash verification-portal/start_portal.sh",
            "  Then open http://127.0.0.1:8000",
            "  First run creates .venv and installs requirements.txt.",
            "",
            "Optional AI backends",
            "  retrieval : all-MiniLM-L6-v2 + FAISS when sentence-transformers/faiss-cpu",
            "              are installed, otherwise a built-in hashing embedder",
            "  generator : DeepSeek API (DEEPSEEK_API_KEY) or local Ollama",
            "              (OLLAMA_BASE_URL, model qwen2.5:3b), otherwise an offline",
            "              deterministic engine. Unreachable backend = graceful fallback.",
            "",
            "Tests",
            "  python scripts/run_all_tests.py      (module-by-module, isolated)",
            "",
            "Note on data/: the bundle deliberately carries no data/ directory.",
            "verification-portal/data is recreated on first start: a fresh demo chain",
            "is seeded and a fresh signer key pair is generated locally, so nothing",
            "here contains stored personal data or anyone's private key. The cost is",
            "that a fresh clone starts at chain height 3-ish rather than showing the",
            "credentials issued during development.",
            "",
            f"Files: {len(manifest)}",
        ]
        zf.writestr(f"{ARC_ROOT}/PACKAGE_CONTENTS.txt", "\n".join(contents))
        manifest.append((f"{ARC_ROOT}/PACKAGE_CONTENTS.txt", 0))

    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"OUT {OUT}")
    print(f"files {len(manifest)}  size {size_mb:.1f} MB")
    top = {}
    for arc, sz in manifest:
        parts = arc.split("/")
        key = "/".join(parts[1:3]) if len(parts) > 2 else parts[-1]
        top[key] = top.get(key, 0) + sz
    for key, sz in sorted(top.items(), key=lambda kv: -kv[1])[:14]:
        print(f"  {sz/1024/1024:7.2f} MB  {key}")
    return verify_bundle(OUT)


if __name__ == "__main__":
    raise SystemExit(main())
