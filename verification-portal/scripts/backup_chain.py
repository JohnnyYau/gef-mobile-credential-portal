#!/usr/bin/env python3
"""backup_chain.py — export / import the chain directory (free-tier
persistence). The export is a single gzip tar of the chain directory: block
files, info.yaml, the signer key registry, rawjsondocs/ (needed for PDF
lookup + RAG) and the active-signer marker. Private keys are included by
default so the exported chain keeps issuing; use --exclude-keys to export a
verification-only snapshot.

Usage:
    python scripts/backup_chain.py export --dir data/demo-chain --out chain-backup.tar.gz
    python scripts/backup_chain.py import --dir data/demo-chain --in chain-backup.tar.gz

Import refuses to overwrite an existing chain directory (restore into an
empty path, or delete the old chain first). Import also validates every member
path (no absolute paths, no '..') so a tampered archive cannot write outside
the chain directory.
"""

import argparse
import io
import os
import sys
import tarfile
from pathlib import Path

# Allow running from the repo without installing: scripts/ -> portal root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config as cfg  # noqa: E402

INFO_FILE = "info.yaml"
PRIVATE_KEY_GLOB = "keys/*.priv.pem"


def _members_for_export(chain_dir: Path, exclude_keys: bool) -> list[str]:
    members = []
    for p in sorted(chain_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(chain_dir).as_posix()
        if exclude_keys and rel.startswith("keys/"):
            continue
        if rel.endswith(".tmp"):
            continue  # never include half-written files
        members.append(rel)
    if not members or INFO_FILE not in members:
        print(f"warning: no {INFO_FILE} found under {chain_dir} — "
              "this does not look like a chain directory", file=sys.stderr)
    return members


def export_chain(chain_dir: Path, out_path: Path, exclude_keys: bool) -> None:
    chain_dir = chain_dir.resolve()
    members = _members_for_export(chain_dir, exclude_keys)
    with tarfile.open(out_path, "w:gz") as tf:
        for rel in members:
            full = chain_dir / rel
            tf.add(full, arcname=rel)
    print(f"ok: exported {len(members)} files -> {out_path}")


def import_chain(chain_dir: Path, in_path: Path) -> None:
    chain_dir = chain_dir.resolve()
    if chain_dir.exists() and any(chain_dir.iterdir()):
        raise SystemExit(
            f"refusing to import into non-empty chain dir: {chain_dir} — "
            "restore into an empty path or remove the old chain first.")
    chain_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(in_path, "r:gz") as tf:
        members = []
        for member in tf.getmembers():
            p = Path(member.name)
            if p.is_absolute() or ".." in p.parts:
                raise SystemExit(f"unsafe path in archive: {member.name!r} — aborting")
            members.append(member)
        tf.extractall(chain_dir, members=members)
    if not (chain_dir / INFO_FILE).exists():
        print(f"warning: imported archive has no {INFO_FILE} — "
              "this may not be a chain backup", file=sys.stderr)
    print(f"ok: imported {len(members)} files -> {chain_dir}")


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

    args = parser.parse_args()
    if args.command == "export":
        export_chain(Path(args.dir), Path(args.out), args.exclude_keys)
    else:
        import_chain(Path(args.dir), Path(args.in_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
