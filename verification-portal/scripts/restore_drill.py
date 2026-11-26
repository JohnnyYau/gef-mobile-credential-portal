#!/usr/bin/env python3
"""restore_drill.py — rehearse backup → verify → restore → re-verify (U8.1).

A backup nobody restored is a hope, not a plan. This script performs the drill
against a real chain directory and prints one line per step so the result can
be pasted into a report:

    1. export          chain dir → tar.gz (with MANIFEST.json)
    2. verify archive  members + per-file SHA-256, no extraction
    3. import          extract into a *fresh* dir, manifest re-checked
    4. chain replay    verify_chain() on the restored copy
    5. credential      look up an on-chain hash in the restored copy and
                       compare its lifecycle against the source

Usage:
    python scripts/restore_drill.py
    python scripts/restore_drill.py --dir data/demo-chain --keep

Exit code 0 only if every step passes. ``--keep`` leaves the temporary
snapshot + restored dir in place for inspection.
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import backup, blockchain_util  # noqa: E402
from app import config as cfg
from scripts.backup_chain import export_chain, import_chain  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def _step(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def _first_issue_hash(chain: Path) -> str | None:
    """Oldest ISSUE payload on the chain: a stable credential to compare."""
    try:
        height = blockchain_util.last_height(str(chain))
    except Exception:                                    # noqa: BLE001 - reported
        return None
    for h in range(1, height + 1):
        try:
            block = blockchain_util.load_block(str(chain), h)
        except Exception:                                # noqa: BLE001 - skip
            continue
        payload = block.get("payload") or {}
        if payload.get("action") == "ISSUE" and payload.get("HashedDocument"):
            return payload["HashedDocument"]
    return None


def run(source: Path, keep: bool) -> int:
    source = source.resolve()
    if not source.is_dir():
        print(f"error: chain dir not found: {source}", file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix="gef26-drill-"))
    archive = work / "snapshot.tar.gz"
    restored = work / "restored-chain"

    try:
        rc = export_chain(source, archive, exclude_keys=False)
        _step("export", rc == 0, f"{archive.name} ({archive.stat().st_size} B)"
              if archive.exists() else "no archive produced")

        ok, manifest, problems = backup.verify_archive(archive)
        _step("verify archive", ok,
              f"height={manifest.get('height')} files={len(manifest.get('files', []))}"
              if manifest else "; ".join(problems))

        rc = import_chain(restored, archive)
        _step("import", rc == 0 and (restored / "info.yaml").is_file(),
              f"restored {len(list(restored.rglob('*')))} entries"
              if restored.exists() else "no target dir")

        chain_ok, detail = blockchain_util.verify_chain(str(restored))
        _step("chain replay", chain_ok,
              "clean" if chain_ok else f"{len(detail)} problem(s): {detail[:1]}")

        cred = _first_issue_hash(source)
        if cred is None:
            _step("credential comparison", True, "no ISSUE block to compare (empty chain)")
        else:
            before = blockchain_util.fetch_status(str(source), cred)
            after = blockchain_util.fetch_status(str(restored), cred)
            same = (before == after)
            _step("credential comparison", same,
                  f"hash {cred[:8]}… issued={after.get('issued')} "
                  f"revoked={after.get('revoked')} "
                  f"issue_heights={after.get('issue_heights')}")

        heights_match = (blockchain_util.last_height(str(source))
                         == blockchain_util.last_height(str(restored)))
        _step("height matches", heights_match,
              f"{blockchain_util.last_height(str(source))} → "
              f"{blockchain_util.last_height(str(restored))}")
    finally:
        if keep:
            print(f"kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    failures = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failures)}/{len(RESULTS)} drill steps passed")
    return 0 if not failures else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=str(cfg.CHAIN_DIR), help="source chain directory")
    ap.add_argument("--keep", action="store_true", help="keep the temp snapshot")
    args = ap.parse_args()
    return run(Path(args.dir), args.keep)


if __name__ == "__main__":
    raise SystemExit(main())
