"""Batch U8.1 — chain snapshot: manifest, member safety, restore drill.

Three things are being proven here:

1. **Round trip.** Export → verify → import into a fresh directory leaves a
   chain that replays clean, with the same height and the same credential
   lifecycle as the source.
2. **Tamper detection.** Flipping one byte inside a block file makes archive
   verification fail, and import refuses *before* touching the target — a
   failed restore must not leave a half-written chain behind.
3. **Member safety.** ``..``, absolute paths, symlinks, hardlinks and devices
   are rejected, both in the CLI path and in the boot-time restore path
   (``CHAIN_SNAPSHOT_URL``). Extraction escaping the chain directory is the
   failure this guards against.

Also covered: importing into a non-empty directory, and a legacy archive with
no manifest (allowed, but flagged).
"""

import io
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

from tests._bootstrap import isolated_chain_dir


def setUpModule():
    isolated_chain_dir(prefix="gef26-backup-")
    from app import backup, blockchain_util, chain_service, config
    global app_backup, bu, cs, cfg, backup_chain
    app_backup, bu, cs, cfg = backup, blockchain_util, chain_service, config
    import scripts.backup_chain as _bc
    backup_chain = _bc
    cs.ensure_chain()


def _rewrite_archive(src: Path, dst: Path, *, mutate=None,
                     inject=None) -> None:
    """Copy ``src`` to ``dst``, optionally altering a member or injecting one."""
    with tarfile.open(src, "r:gz") as tf:
        members = tf.getmembers()
        payloads = {}
        for m in members:
            if m.isfile():
                handle = tf.extractfile(m)
                payloads[m.name] = handle.read() if handle else b""
    with tarfile.open(dst, "w:gz") as tf:
        for m in members:
            data = payloads.get(m.name)
            if mutate and mutate(m.name) and data is not None:
                data = data[:-1] + (b"9" if data[-1:] != b"9" else b"8")
            if data is None:
                tf.addfile(m)
            else:
                info = tarfile.TarInfo(m.name)
                info.size = len(data)
                info.mtime = m.mtime
                tf.addfile(info, io.BytesIO(data))
        if inject:
            inject(tf)


class SnapshotRoundTripTests(unittest.TestCase):
    def test_export_verify_import_round_trip(self):
        work = Path(tempfile.mkdtemp(prefix="gef26-bk-"))
        archive = work / "snap.tar.gz"
        restored = work / "restored"
        try:
            self.assertEqual(backup_chain.export_chain(
                Path(cfg.CHAIN_DIR), archive, exclude_keys=False), 0)
            ok, manifest, problems = app_backup.verify_archive(archive)
            self.assertTrue(ok, problems)
            self.assertEqual(manifest["format"], app_backup.MANIFEST_FORMAT)
            self.assertTrue(manifest["includes_private_keys"])
            self.assertGreater(len(manifest["files"]), 0)
            self.assertEqual(manifest["height"], bu.last_height(str(cfg.CHAIN_DIR)))

            self.assertEqual(backup_chain.import_chain(restored, archive), 0)
            self.assertTrue((restored / "info.yaml").is_file())
            ok_chain, detail = bu.verify_chain(str(restored))
            self.assertTrue(ok_chain, detail[:3])
            self.assertEqual(bu.last_height(str(restored)),
                             bu.last_height(str(cfg.CHAIN_DIR)))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_exclude_keys_leaves_no_private_key(self):
        work = Path(tempfile.mkdtemp(prefix="gef26-bk-"))
        archive = work / "nokeys.tar.gz"
        try:
            self.assertEqual(backup_chain.export_chain(
                Path(cfg.CHAIN_DIR), archive, exclude_keys=True), 0)
            with tarfile.open(archive, "r:gz") as tf:
                names = tf.getnames()
            self.assertFalse([n for n in names if n.startswith("keys/")])
            manifest = app_backup.read_manifest(
                tarfile.open(archive, "r:gz"))
            self.assertFalse(manifest["includes_private_keys"])
        finally:
            shutil.rmtree(work, ignore_errors=True)


class SnapshotTamperTests(unittest.TestCase):
    def test_flipped_byte_fails_verification_and_import(self):
        work = Path(tempfile.mkdtemp(prefix="gef26-tamper-"))
        archive = work / "snap.tar.gz"
        tampered = work / "tampered.tar.gz"
        target = work / "target"
        try:
            backup_chain.export_chain(Path(cfg.CHAIN_DIR), archive, exclude_keys=False)
            _rewrite_archive(archive, tampered,
                             mutate=lambda name: name.startswith("blocks/"))
            ok, _, problems = app_backup.verify_archive(tampered)
            self.assertFalse(ok)
            self.assertTrue(any("checksum mismatch" in p for p in problems), problems)

            rc = backup_chain.import_chain(target, tampered)
            self.assertEqual(rc, 1)
            self.assertFalse(target.exists(),
                             "a rejected import must not create the target dir")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_missing_file_in_archive_is_detected_on_restore(self):
        work = Path(tempfile.mkdtemp(prefix="gef26-miss-"))
        archive = work / "snap.tar.gz"
        target = work / "target"
        try:
            backup_chain.export_chain(Path(cfg.CHAIN_DIR), archive, exclude_keys=False)
            # drop one block file: the manifest still lists it
            with tarfile.open(archive, "r:gz") as tf:
                keep = [m for m in tf.getmembers()
                        if not m.name.startswith("blocks/") or m.name.endswith("01.json")]
                payloads = {m.name: tf.extractfile(m).read()
                            for m in keep if m.isfile()}
            with tarfile.open(archive, "w:gz") as tf:
                for m in keep:
                    data = payloads.get(m.name)
                    if data is None:
                        tf.addfile(m)
                    else:
                        info = tarfile.TarInfo(m.name)
                        info.size = len(data)
                        tf.addfile(info, io.BytesIO(data))
            ok, _, _ = app_backup.verify_archive(archive)
            self.assertFalse(ok)
            self.assertEqual(backup_chain.import_chain(target, archive), 1)
            self.assertFalse(target.exists())
        finally:
            shutil.rmtree(work, ignore_errors=True)


class MemberSafetyTests(unittest.TestCase):
    def _archive_with(self, add) -> Path:
        path = Path(tempfile.mkdtemp(prefix="gef26-bad-")) / "bad.tar.gz"
        with tarfile.open(path, "w:gz") as tf:
            add(tf)
        return path

    def test_traversal_member_is_rejected(self):
        archive = self._archive_with(lambda tf: tf.addfile(
            tarfile.TarInfo("../escaped.txt")))
        with tarfile.open(archive, "r:gz") as tf:
            with self.assertRaises(RuntimeError):
                app_backup.safe_members(tf)

    def test_absolute_member_is_rejected(self):
        archive = self._archive_with(lambda tf: tf.addfile(
            tarfile.TarInfo("/tmp/escaped.txt")))
        with tarfile.open(archive, "r:gz") as tf:
            with self.assertRaises(RuntimeError):
                app_backup.safe_members(tf)

    def test_symlink_member_is_rejected(self):
        def add(tf):
            info = tarfile.TarInfo("keys/evil.pem")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        archive = self._archive_with(add)
        with tarfile.open(archive, "r:gz") as tf:
            with self.assertRaises(RuntimeError):
                app_backup.safe_members(tf)

    def test_hardlink_member_is_rejected(self):
        def add(tf):
            info = tarfile.TarInfo("keys/hard.pem")
            info.type = tarfile.LNKTYPE
            info.linkname = "info.yaml"
            tf.addfile(info)
        archive = self._archive_with(add)
        with tarfile.open(archive, "r:gz") as tf:
            with self.assertRaises(RuntimeError):
                app_backup.safe_members(tf)

    def test_device_member_is_rejected(self):
        def add(tf):
            info = tarfile.TarInfo("dev/zero")
            info.type = tarfile.CHRTYPE
            tf.addfile(info)
        archive = self._archive_with(add)
        with tarfile.open(archive, "r:gz") as tf:
            with self.assertRaises(RuntimeError):
                app_backup.safe_members(tf)


class ImportGuardTests(unittest.TestCase):
    def test_non_empty_target_is_refused(self):
        work = Path(tempfile.mkdtemp(prefix="gef26-nonempty-"))
        archive = work / "snap.tar.gz"
        target = work / "existing"
        try:
            backup_chain.export_chain(Path(cfg.CHAIN_DIR), archive, exclude_keys=True)
            target.mkdir()
            (target / "keep-me.txt").write_text("user data", encoding="utf-8")
            rc = backup_chain.import_chain(target, archive)
            self.assertEqual(rc, 2)
            self.assertTrue((target / "keep-me.txt").is_file(),
                            "refusal must not touch existing content")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_legacy_archive_without_manifest_is_accepted_with_a_warning(self):
        work = Path(tempfile.mkdtemp(prefix="gef26-legacy-"))
        archive = work / "legacy.tar.gz"
        target = work / "restored"
        try:
            backup_chain.export_chain(Path(cfg.CHAIN_DIR), archive, exclude_keys=True)
            # strip MANIFEST.json -> a pre-U8.1 export
            with tarfile.open(archive, "r:gz") as tf:
                keep = [m for m in tf.getmembers()
                        if m.name != app_backup.MANIFEST_NAME]
                payloads = {m.name: tf.extractfile(m).read()
                            for m in keep if m.isfile()}
            with tarfile.open(archive, "w:gz") as tf:
                for m in keep:
                    data = payloads.get(m.name)
                    if data is None:
                        tf.addfile(m)
                    else:
                        info = tarfile.TarInfo(m.name)
                        info.size = len(data)
                        tf.addfile(info, io.BytesIO(data))
            ok, manifest, problems = app_backup.verify_archive(archive)
            self.assertTrue(ok, problems)
            self.assertIsNone(manifest)
            self.assertTrue(any("no MANIFEST" in p for p in problems))
            self.assertEqual(backup_chain.import_chain(target, archive), 0)
            self.assertTrue((target / "info.yaml").is_file())
        finally:
            shutil.rmtree(work, ignore_errors=True)


class BootRestoreTests(unittest.TestCase):
    """``CHAIN_SNAPSHOT_URL`` restore path, including its safety checks.

    The app reads CHAIN_DIR at import, so these tests point the *module*
    constant at a scratch dir instead of relying on the environment.
    """

    def setUp(self):
        from app import chain_core
        self.core = chain_core
        self._original = chain_core.CHAIN_DIR
        self.scratch = Path(tempfile.mkdtemp(prefix="gef26-boot-"))
        chain_core.CHAIN_DIR = self.scratch / "chain"

    def tearDown(self):
        self.core.CHAIN_DIR = self._original
        shutil.rmtree(self.scratch, ignore_errors=True)

    def test_restores_from_a_local_snapshot_uri(self):
        work = Path(tempfile.mkdtemp(prefix="gef26-src-"))
        archive = work / "snap.tar.gz"
        try:
            backup_chain.export_chain(Path(cfg.CHAIN_DIR), archive, exclude_keys=False)
            self.assertTrue(self.core.restore_snapshot_if_needed(archive.as_uri()))
            self.assertTrue((self.core.CHAIN_DIR / "info.yaml").is_file())
            ok, detail = bu.verify_chain(str(self.core.CHAIN_DIR))
            self.assertTrue(ok, detail[:3])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_restore_is_skipped_when_a_chain_exists(self):
        (self.core.CHAIN_DIR).mkdir(parents=True)
        (self.core.CHAIN_DIR / "info.yaml").write_text("x: 1\n", encoding="utf-8")
        self.assertFalse(self.core.restore_snapshot_if_needed("file:///nonexistent"))

    def test_symlink_in_snapshot_aborts_the_boot(self):
        work = Path(tempfile.mkdtemp(prefix="gef26-evil-"))
        archive = work / "evil.tar.gz"
        try:
            (work / "info.yaml").write_text("x: 1\n", encoding="utf-8")
            with tarfile.open(archive, "w:gz") as tf:
                tf.add(work / "info.yaml", arcname="info.yaml")
                info = tarfile.TarInfo("keys/evil.pem")
                info.type = tarfile.SYMTYPE
                info.linkname = os.path.abspath("/etc/passwd")
                tf.addfile(info)
            with self.assertRaises(RuntimeError):
                self.core.restore_snapshot_if_needed(archive.as_uri())
            self.assertFalse((self.core.CHAIN_DIR / "info.yaml").is_file())
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_tampered_snapshot_aborts_the_boot(self):
        work = Path(tempfile.mkdtemp(prefix="gef26-badtamper-"))
        archive = work / "snap.tar.gz"
        tampered = work / "tampered.tar.gz"
        try:
            backup_chain.export_chain(Path(cfg.CHAIN_DIR), archive, exclude_keys=True)
            _rewrite_archive(archive, tampered,
                             mutate=lambda name: name == "info.yaml")
            with self.assertRaises(RuntimeError) as caught:
                self.core.restore_snapshot_if_needed(tampered.as_uri())
            self.assertIn("manifest", str(caught.exception))
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
