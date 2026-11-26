"""Batch U9-A — chain read caches must not turn into stale verdicts.

The cache is safe because it is keyed on a fingerprint of the block directory
(count, total size, newest mtime): append / rewrite / truncate all change it,
so `verify_document()` cannot report VALID from a cached replay of a chain that
has since been edited. The TTL is the only window in which a
*fingerprint-preserving* edit (same size, mtime restored) could hide — these
tests pin down both properties, including the TTL bound itself.
"""

import os
import re
import time
import unittest
from pathlib import Path

from tests._bootstrap import isolated_chain_dir


def setUpModule():
    isolated_chain_dir(prefix="gef26-u9a-")
    import app.blockchain_util as bu
    import app.chain_service as cs
    import app.config as cfg
    global blockchain_util, cfg_mod, chain_service
    blockchain_util, cfg_mod, chain_service = bu, cfg, cs
    chain_service.ensure_chain()


def _doc(index: int) -> dict:
    return {
        "PersonalParticulars": {
            "Surname": f"CACH{index:03d}",
            "GivenNames": "CACHE TEST",
            "StudentID": f"9040{index:04d}",
            "Sex": "F",
            "DOB": "19990101",
        },
        "AcademicInfo": {
            "DegreeName": f"Cache Degree {index}",
            "DegreeStartDate": "20220901",
            "DegreeEndDate": "20260801",
            "Honour": "Pass",
        },
        "DocumentInfo": {
            "DocType": "Diploma",
            "IssuingO": "UNIVERSITY OF UTOPIA",
            "IssuingOU": "FACULTY OF ENGINEERING",
            "DateOfIssue": "20260901",
            "AuthorizedSignature": "REGISTRAR",
        },
    }


def _tamper_block(chain_addr: str, height: int, *, preserve_stat: bool) -> tuple:
    """Rewrite one block so it no longer verifies, keeping the byte length.

    Only the first character of the stored document hash changes, so the file
    keeps its exact size and — when ``preserve_stat`` is set — its original
    mtime. That is precisely the edit the fingerprint cannot see. Returns
    ``(path, original_bytes, stat)`` so the test can restore the chain.
    """
    path = Path(blockchain_util._block_path(chain_addr, height))
    stat = path.stat()
    original = path.read_bytes()
    text = original.decode("utf-8")
    match = re.search(r'("HashedDocument"\s*:\s*")([A-Za-z0-9_\-]+)', text)
    if match is None:
        raise AssertionError(f"no HashedDocument in block {height}: {text[:200]}")
    old = match.group(2)
    new = ("B" if old[0] != "B" else "C") + old[1:]
    mutated = text[:match.start(2)] + new + text[match.end(2):]
    assert len(mutated) == len(text), "tamper must keep the byte length"
    path.write_bytes(mutated.encode("utf-8"))
    if preserve_stat:
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    return path, original, stat


def _restore_block(path: Path, original: bytes, stat) -> None:
    path.write_bytes(original)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    blockchain_util.invalidate_caches(str(chain_service.CHAIN_DIR))


class VerifyChainCacheTests(unittest.TestCase):
    def setUp(self):
        blockchain_util.invalidate_caches(str(chain_service.CHAIN_DIR))

    def test_append_is_visible_without_waiting_for_the_ttl(self):
        chain = str(chain_service.CHAIN_DIR)
        ok_before, report_before = blockchain_util.verify_chain(chain)
        self.assertTrue(ok_before)
        chain_service.issue(_doc(1))            # appends one ISSUE block
        ok_after, report_after = blockchain_util.verify_chain(chain)
        self.assertTrue(ok_after)
        self.assertEqual(len(report_after), len(report_before) + 1,
                         "a new block must invalidate the cached replay")

    def test_tampered_block_breaks_the_cached_verdict(self):
        chain = str(chain_service.CHAIN_DIR)
        self.assertTrue(blockchain_util.verify_chain(chain)[0])
        path, original, stat = _tamper_block(chain, 1, preserve_stat=False)
        try:
            ok, report = blockchain_util.verify_chain(chain)
            self.assertFalse(ok, "a rewritten block must invalidate the cache")
            self.assertTrue(any(not r["ok"] for r in report))
            verdict = blockchain_util.verify_document(chain, _doc(0))
            self.assertFalse(verdict["chain_integrity"],
                             "verify_document must re-replay, not reuse the cache")

            # an unreadable (unparseable) block is the harsher case and must
            # raise — that is what maps to CHAIN DATA CORRUPT / 503
            Path(blockchain_util._block_path(chain, 1)).write_text(
                "{ not json", encoding="utf-8")
            with self.assertRaises(blockchain_util.ChainDataError):
                blockchain_util.verify_document(chain, _doc(0))
        finally:
            _restore_block(path, original, stat)
            self.assertTrue(blockchain_util.verify_chain(chain)[0],
                            "the restored chain must replay clean again")

    def test_fingerprint_preserving_tamper_is_bounded_by_the_ttl(self):
        """The documented residual risk: same size + restored mtime."""
        chain = str(chain_service.CHAIN_DIR)
        original_ttl = cfg_mod.CHAIN_INTEGRITY_TTL
        # 0.5 s, not 0.05 s: one cold scan of this chain takes ~30-240 ms, so a
        # TTL in that range would be measuring the machine's speed, not the
        # cache. (That is exactly how this test became flaky.)
        cfg_mod.CHAIN_INTEGRITY_TTL = 0.5
        try:
            blockchain_util.invalidate_caches(chain)
            self.assertTrue(blockchain_util.verify_chain(chain)[0])
            path, original, stat = _tamper_block(chain, 1, preserve_stat=True)
            try:
                self.assertTrue(blockchain_util.verify_chain(chain)[0],
                                "same fingerprint + live TTL: cached replay")
                time.sleep(0.7)
                self.assertFalse(blockchain_util.verify_chain(chain)[0],
                                 "the TTL must expire and force a real replay")
            finally:
                _restore_block(path, original, stat)
        finally:
            cfg_mod.CHAIN_INTEGRITY_TTL = original_ttl
            blockchain_util.invalidate_caches(chain)

    def test_a_ttl_shorter_than_the_scan_stores_nothing(self):
        """A verdict that expires while it is being computed must not be kept."""
        chain = str(chain_service.CHAIN_DIR)
        original_ttl = cfg_mod.CHAIN_INTEGRITY_TTL
        cfg_mod.CHAIN_INTEGRITY_TTL = 0.0  # disables the cache entirely...
        try:
            blockchain_util.invalidate_caches(chain)
            blockchain_util.verify_chain(chain)
            self.assertNotIn(chain, blockchain_util._CHAIN_CACHE,
                             "TTL 0 must not populate the cache")
            # ...and a TTL far below one scan must not leave a born-expired
            # entry behind either.
            cfg_mod.CHAIN_INTEGRITY_TTL = 0.0001
            blockchain_util.invalidate_caches(chain)
            blockchain_util.verify_chain(chain)
            self.assertNotIn(chain, blockchain_util._CHAIN_CACHE,
                             "a scan slower than its TTL must not cache")
        finally:
            cfg_mod.CHAIN_INTEGRITY_TTL = original_ttl
            blockchain_util.invalidate_caches(chain)


class StatusIndexTests(unittest.TestCase):
    def setUp(self):
        blockchain_util.invalidate_caches(str(chain_service.CHAIN_DIR))

    def test_index_reports_issue_heights(self):
        chain = str(chain_service.CHAIN_DIR)
        creds = chain_service.demo_credentials()
        hashed = creds["diploma"]["hashed_document"]
        status = blockchain_util.fetch_status(chain, hashed)
        self.assertTrue(status["issued"])
        self.assertTrue(status["issue_heights"])
        self.assertEqual(status["issue_heights"], sorted(status["issue_heights"]))

    def test_unknown_hash_has_empty_heights(self):
        status = blockchain_util.fetch_status(
            str(chain_service.CHAIN_DIR), "A" * 86)
        self.assertEqual(status, {"issued": False, "revoked": False,
                                  "issue_heights": [], "revoke_heights": [],
                                  "issued_at": None})

    def test_revoke_append_is_reflected(self):
        chain = str(chain_service.CHAIN_DIR)
        hashed = chain_service.issue(_doc(2))["hashed_document"]
        before = blockchain_util.fetch_status(chain, hashed)
        self.assertTrue(before["issued"])
        self.assertFalse(before["revoked"])
        chain_service.revoke(hashed, reason="u9a test")
        after = blockchain_util.fetch_status(chain, hashed)
        self.assertTrue(after["revoked"])
        self.assertTrue(after["revoke_heights"])
        self.assertEqual(after["issue_heights"], before["issue_heights"])


class InfoCacheTests(unittest.TestCase):
    def test_read_info_sees_a_write(self):
        chain = str(chain_service.CHAIN_DIR)
        name = blockchain_util.read_info(chain)["chain_name"]
        info = blockchain_util.read_info(chain)
        info["chain_name"] = f"{name}-u9a"
        try:
            blockchain_util.write_info(chain, info)
            self.assertEqual(blockchain_util.read_info(chain)["chain_name"],
                             f"{name}-u9a",
                             "info.yaml cache must follow the atomic rewrite")
        finally:
            info["chain_name"] = name
            blockchain_util.write_info(chain, info)
            blockchain_util.invalidate_caches(chain)

    def test_read_info_returns_an_independent_copy(self):
        chain = str(chain_service.CHAIN_DIR)
        info = blockchain_util.read_info(chain)
        info["chain_name"] = "mutated by caller"
        self.assertNotEqual(blockchain_util.read_info(chain)["chain_name"],
                            "mutated by caller")


class CacheControlTests(unittest.TestCase):
    def test_invalidate_caches_accepts_a_single_chain(self):
        blockchain_util.invalidate_caches()
        blockchain_util.verify_chain(str(chain_service.CHAIN_DIR))
        self.assertEqual(len(blockchain_util._CHAIN_CACHE), 1)
        blockchain_util.invalidate_caches(str(chain_service.CHAIN_DIR))
        self.assertEqual(len(blockchain_util._CHAIN_CACHE), 0)
        blockchain_util.read_info(str(chain_service.CHAIN_DIR))
        blockchain_util.invalidate_caches()
        self.assertEqual(len(blockchain_util._INFO_CACHE), 0)


if __name__ == "__main__":
    unittest.main()
