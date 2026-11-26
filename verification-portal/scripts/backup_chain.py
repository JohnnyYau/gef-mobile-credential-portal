#!/usr/bin/env python3
"""backup_chain.py — export / verify / import the chain directory (U8.1).

The export is a single gzip tar of the chain directory (block files, info.yaml,
the signer key registry, rawjsondocs/ and the active-signer marker) plus a
``MANIFEST.json`` describing chain name, height, whether private keys are
included, and a SHA-256 per file. Private keys are included by default so the
restored chain can keep issuing; ``--exclude-keys`` produces a
verification-only snapshot.

Usage:
    python scripts/backup_chain.py export --dir data/demo-chain --out chain-backup.tar.gz
    python scripts/backup_chain.py verify --in chain-backup.tar.gz
    python scripts/backup_chain.py import --dir data/demo-chain --in chain-backup.tar.gz

Import restores into a sibling ``<dir>.restoring`` first, verifies the
manifest there, and only then renames into place — a failed import leaves the
target untouched instead of a half-written chain. It refuses a non-empty
target. Archive members that are absolute, contain ``..``, or are symlinks /
hardlinks / devices are rejected (see ``app/backup.py``).
"""

import argparse
import io
import shutil
import sys
import tarfile
import time
from pathlib import Path

# Allow running from the repo without installing: scripts/ -> portal root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import (
    backup,  # noqa: E402
    blockchain_util,  # noqa: E402
)
from app import config as cfg  # noqa: E402


def _chain_facts(chain_dir: Path) -> tuple[str | None, int | None]:
    """Chain name + height for the manifest; never fatal (a corrupt chain still
    deserves a backup, it just gets a manifest that says so)."""
    try:
        info = blockchain_util.read_info(str(chain_dir))
        return info.get("chain_name"), blockchain_util.last_height(str(chain_dir))
    except Exception:                                   # noqa: BLE001 - reported
        return None, None


def _members_for_export(chain_dir: Path, exclude_keys: bool) -> list[str]:
    members = []
    for p in sorted(chain_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(chain_dir).as_posix()
        if exclude_keys and rel.startswith("keys/"):
            continue
        if rel.endswith(".tmp"):
            continue                                   # never half-written files
        if rel == backup.MANIFEST_NAME:
            continue                                   # regenerated below
        members.append(rel)
    if not members or backup.INFO_FILE not in members:
        print(f"warning: no {backup.INFO_FILE} found under {chain_dir} — "
              "this does not look like a chain directory", file=sys.stderr)
    return members


def export_chain(chain_dir: Path, out_path: Path, exclude_keys: bool) -> int:
    chain_dir = chain_dir.resolve()
    out_path = out_path.resolve()
    if not chain_dir.is_dir():
        print(f"error: chain dir does not exist: {chain_dir}", file=sys.stderr)
        return 2
    if chain_dir in out_path.parents or out_path == chain_dir:
        print("error: --out must not be inside the chain directory "
              "(the archive would try to include itself)", file=sys.stderr)
        return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)

    members = _members_for_export(chain_dir, exclude_keys)
    name, height = _chain_facts(chain_dir)
    manifest = backup.build_manifest(
        chain_dir, members,
        includes_private_keys=not exclude_keys,
        chain_name=name, height=height)

    with tarfile.open(out_path, "w:gz") as tf:
        for rel in members:
            tf.add(chain_dir / rel, arcname=rel)
        data = backup.manifest_bytes(manifest)
        info = tarfile.TarInfo(backup.MANIFEST_NAME)
        info.size = len(data)
        info.mtime = int(time.time())
        tf.addfile(info, io.BytesIO(data))

    ok, _, problems = backup.verify_archive(out_path)
    print(f"ok: exported {len(members)} files -> {out_path}")
    print(f"    manifest: chain={name} height={height} "
          f"keys={'no' if exclude_keys else 'yes'} files={len(manifest['files'])}")
    if not ok:
        print("error: the archive just written failed its own verification:",
              file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        return 1
    return 0


def import_chain(chain_dir: Path, in_path: Path) -> int:
    chain_dir = chain_dir.resolve()
    in_path = in_path.resolve()
    if not in_path.is_file():
        print(f"error: archive not found: {in_path}", file=sys.stderr)
        return 2
    if chain_dir.exists() and any(chain_dir.iterdir()):
        print(f"error: refusing to import into non-empty chain dir: {chain_dir} — "
              "restore into an empty path or remove the old chain first.",
              file=sys.stderr)
        return 2

    ok, manifest, problems = backup.verify_archive(in_path)
    if not ok:
        print("error: archive failed verification, nothing was restored:",
              file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        return 1

    staging = chain_dir.with_name(chain_dir.name + ".restoring")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with tarfile.open(in_path, "r:gz") as tf:
            count = backup.extract_safely(tf, staging)
        if manifest is not None:
            restored = backup.audit_restored(staging, manifest)
            if restored:
                print("error: restored tree does not match its manifest:",
                      file=sys.stderr)
                for line in restored:
                    print(f"  - {line}", file=sys.stderr)
                return 1
        elif not (staging / backup.INFO_FILE).is_file():
            print(f"error: imported archive has no {backup.INFO_FILE} — "
                  "this may not be a chain backup", file=sys.stderr)
            return 1
        if chain_dir.exists():
            chain_dir.rmdir()                          # empty by the check above
        staging.rename(chain_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    height = manifest.get("height") if manifest else None
    print(f"ok: imported {count} files -> {chain_dir}"
          + (f" (height {height}, checksums verified)" if manifest
             else " (no manifest: members were validated, contents were not)"))
    return 0


def verify_chain_archive(in_path: Path) -> int:
    ok, manifest, problems = backup.verify_archive(in_path.resolve())
    if ok:
        print(f"ok: {in_path} verifies"
              + (f" (height {manifest.get('height')}, "
                 f"{len(manifest.get('files', []))} files)"
                 if manifest else " (no manifest)"))
        return 0
    print(f"FAIL: {in_path} did not verify:", file=sys.stderr)
    for line in problems:
        print(f"  - {line}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("export", help="export chain dir to a tar.gz")
    ex.add_argument("--dir", default=str(cfg.CHAIN_DIR))
    ex.add_argument("--out", required=True)
    ex.add_argument("--exclude-keys", action="store_true",
                    help="omit keys/*.priv.pem (verification-only snapshot)")

    im = sub.add_parser("import", help="import a tar.gz into an empty chain dir")
    im.add_argument("--dir", default=str(cfg.CHAIN_DIR))
    im.add_argument("--in", dest="in_path", required=True)

    ve = sub.add_parser("verify", help="check members + checksums, no extraction")
    ve.add_argument("--in", dest="in_path", required=True)

    args = parser.parse_args()
    if args.command == "export":
        return export_chain(Path(args.dir), Path(args.out), args.exclude_keys)
    if args.command == "import":
        return import_chain(Path(args.dir), Path(args.in_path))
    return verify_chain_archive(Path(args.in_path))


if __name__ == "__main__":
    raise SystemExit(main())
