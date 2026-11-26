"""backup.py — chain snapshot archive: manifest + member safety (batch U8.1).

A backup is only useful if restoring it proves the archive is the same chain
that was exported. Two failure modes drove this module:

1. **Path escape.** The old import validated only ``..`` and absolute paths.
   A tar member can also be a *symlink* or a *hardlink*, which ``extractall``
   will create happily; a following member can then be written through it and
   land outside the chain directory. ``safe_members()`` rejects links, devices
   and FIFOs, and extraction goes through ``filter="data"`` where the runtime
   supports it (PEP 706, Python 3.12+).

2. **Silent partial restores.** Without a checksum list, "restored" only ever
   meant "the tarball opened". ``MANIFEST.json`` records the chain name,
   height and a SHA-256 per file, so import can prove every byte and refuse
   a truncated or hand-edited snapshot instead of booting on top of it.

The manifest is optional on read (older exports predate it), but when it is
present a mismatch is fatal — a half-verified chain is worse than no chain.
"""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
import time
from pathlib import Path
from typing import Any

MANIFEST_NAME = "MANIFEST.json"
MANIFEST_FORMAT = "gef26-chain-snapshot-v1"
INFO_FILE = "info.yaml"

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _is_unsafe_path(name: str) -> bool:
    """True for any member name that could land outside the target directory.

    ``Path.is_absolute()`` is platform-specific: on Windows ``/tmp/x`` is *not*
    absolute (no drive), so a Linux-made archive with POSIX absolute paths
    would slip through. Check the shape of the string instead of asking the
    filesystem what it thinks.
    """
    if not name or name.startswith(("/", "\\")):
        return True
    if _DRIVE_RE.match(name) or name.startswith("\\\\"):
        return True
    path = Path(name)
    return path.is_absolute() or ".." in path.parts


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_members(tf: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Return the members that may be extracted, or raise ``RuntimeError``.

    Rejects: absolute paths, ``..`` components, symlinks, hardlinks, character
    and block devices, FIFOs. Directories are allowed (they carry no payload).
    """
    members = []
    for member in tf.getmembers():
        name = member.name
        if _is_unsafe_path(name):
            raise RuntimeError(f"unsafe path in chain snapshot: {name!r}")
        if member.issym() or member.islnk():
            raise RuntimeError(f"link member in chain snapshot: {name!r}")
        if member.isdev() or member.isfifo():
            raise RuntimeError(f"device member in chain snapshot: {name!r}")
        members.append(member)
    return members


def extract_safely(tf: tarfile.TarFile, dest: Path) -> int:
    """Extract only safe members into ``dest``; returns the member count."""
    members = safe_members(tf)
    kwargs: dict[str, Any] = {"members": members}
    try:                                  # Python >= 3.12: rejects links too
        tf.extractall(dest, filter="data", **kwargs)
    except TypeError:                     # older runtime: manual checks above
        tf.extractall(dest, **kwargs)
    return len(members)


def build_manifest(chain_dir: Path, members: list[str], *,
                   includes_private_keys: bool, chain_name: str | None,
                   height: int | None) -> dict[str, Any]:
    """Describe the exported payload so a later import can verify it."""
    files = []
    for rel in members:
        if rel == MANIFEST_NAME:
            continue
        full = chain_dir / rel
        files.append({"path": rel, "size": full.stat().st_size,
                      "sha256": sha256_of(full)})
    return {
        "format": MANIFEST_FORMAT,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chain_name": chain_name,
        "height": height,
        "includes_private_keys": includes_private_keys,
        "files": files,
    }


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n").encode("utf-8")


def read_manifest(tf: tarfile.TarFile) -> dict[str, Any] | None:
    """Return the archive's manifest, or ``None`` for a pre-U8.1 export."""
    try:
        member = tf.getmember(MANIFEST_NAME)
    except KeyError:
        return None
    handle = tf.extractfile(member)
    if handle is None:                    # directory entry, not a file
        return None
    try:
        payload = json.loads(handle.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"chain snapshot manifest is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != MANIFEST_FORMAT:
        raise RuntimeError("chain snapshot manifest has an unknown format")
    return payload


def audit_restored(root: Path, manifest: dict[str, Any],
                   *, require_all: bool = True) -> list[str]:
    """Compare an extracted directory against its manifest.

    Returns a list of human-readable problems (empty list == clean). With
    ``require_all`` every manifest entry must exist; extra files on disk are
    reported too, because an unexpected file inside a chain directory is
    exactly the kind of thing a restore should surface rather than ignore.
    """
    problems: list[str] = []
    listed = {entry["path"]: entry for entry in manifest.get("files", [])}
    for rel, entry in sorted(listed.items()):
        full = root / rel
        if not full.is_file():
            if require_all:
                problems.append(f"missing file: {rel}")
            continue
        if full.stat().st_size != entry.get("size", full.stat().st_size):
            problems.append(f"size mismatch: {rel}")
            continue
        if sha256_of(full) != entry.get("sha256"):
            problems.append(f"checksum mismatch: {rel}")

    on_disk = {p.relative_to(root).as_posix()
               for p in root.rglob("*") if p.is_file()}
    for rel in sorted(on_disk - set(listed) - {MANIFEST_NAME}):
        problems.append(f"unexpected file: {rel}")

    if not (root / INFO_FILE).is_file():
        problems.append(f"missing {INFO_FILE}")
    return problems


def verify_archive(path: Path) -> tuple[bool, dict[str, Any] | None, list[str]]:
    """Open an archive, check members and checksums without extracting.

    Returns ``(ok, manifest, problems)``. Missing manifest is reported as a
    problem *string* but does not fail verification of member safety, so an
    old backup can still be inspected.
    """
    problems: list[str] = []
    manifest: dict[str, Any] | None = None
    try:
        with tarfile.open(path, "r:gz") as tf:
            safe_members(tf)              # raises on unsafe members
            manifest = read_manifest(tf)
            if manifest is None:
                # A pre-U8.1 export cannot be checksum-verified, but that is a
                # limitation, not a failure: say so and still judge the archive
                # on member safety + whether a chain is actually inside.
                notes = ["no MANIFEST.json (pre-U8.1 export): contents not verified"]
                if INFO_FILE not in tf.getnames():
                    return False, None, notes + [f"missing {INFO_FILE}"]
                return True, None, notes
            for entry in manifest.get("files", []):
                try:
                    member = tf.getmember(entry["path"])
                except KeyError:
                    problems.append(f"missing member: {entry['path']}")
                    continue
                handle = tf.extractfile(member)
                if handle is None:
                    problems.append(f"unreadable member: {entry['path']}")
                    continue
                digest = hashlib.sha256(handle.read()).hexdigest()
                if digest != entry.get("sha256"):
                    problems.append(f"checksum mismatch: {entry['path']}")
    except (OSError, tarfile.TarError, RuntimeError) as exc:
        return False, manifest, problems + [str(exc)]
    return not problems, manifest, problems
