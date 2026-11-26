"""Batch U7.1 — issuing and revoking under concurrency.

The chain has one writer lock (``chain_core._lock``), so correctness under
parallelism is about *ordering and completeness*, not about throughput:

* two threads must never produce the same block height (a lost block),
* heights must form an unbroken, duplicate-free sequence,
* a credential revoked while other issuances are in flight must end up
  REVOKED, and every untouched credential must stay VALID ON CHAIN,
* the chain must still replay clean at the end.

Signature schemes are randomised (RSA-PSS salt, ECDSA k), so this test never
compares signature bytes — only structural invariants.
"""

import threading
import unittest

from tests._bootstrap import isolated_chain_dir

ISSUERS = 8
REVOKERS = 3


def _doc(index: int) -> dict:
    return {
        "PersonalParticulars": {
            "Surname": f"CONC{index:03d}",
            "GivenNames": "THREAD TEST",
            "StudentID": f"9030{index:04d}",
            "Sex": "F",
            "DOB": "19990101",
        },
        "AcademicInfo": {
            "DegreeName": f"Concurrency Degree {index}",
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


def setUpModule():
    isolated_chain_dir(prefix="gef26-conc-")
    from app import blockchain_util, chain_service
    global cs, bu
    cs, bu = chain_service, blockchain_util
    cs.ensure_chain()


class ConcurrentIssueRevokeTests(unittest.TestCase):
    def test_parallel_issue_and_revoke_keep_the_chain_consistent(self):
        start_height = bu.last_height(str(cs.CHAIN_DIR))
        # anchors issued *before* the storm, so revokers do not race issuance
        anchors = [cs.issue(_doc(900 + i))["hashed_document"]
                   for i in range(REVOKERS)]
        issued: list[dict] = []
        errors: list[str] = []
        guard = threading.Lock()

        def issue_worker(i: int) -> None:
            try:
                res = cs.issue(_doc(i))
                with guard:
                    issued.append(res)
            except Exception as exc:                    # noqa: BLE001 - reported
                with guard:
                    errors.append(f"issue{i}: {type(exc).__name__}: {exc}")

        def revoke_worker(i: int) -> None:
            try:
                cs.revoke(anchors[i], reason="concurrency test")
            except Exception as exc:                    # noqa: BLE001 - reported
                with guard:
                    errors.append(f"revoke{i}: {type(exc).__name__}: {exc}")

        issuers = [threading.Thread(target=issue_worker, args=(i,))
                   for i in range(ISSUERS)]
        revokers = [threading.Thread(target=revoke_worker, args=(i,))
                    for i in range(REVOKERS)]
        for t in issuers + revokers:
            t.start()
        for t in issuers + revokers:
            t.join(timeout=120)

        self.assertEqual(errors, [], f"threads raised: {errors}")
        self.assertEqual(len(issued), ISSUERS)
        self.assertEqual(len({r["hashed_document"] for r in issued}),
                         ISSUERS, "the same credential was issued twice")

        heights = sorted(r["height"] for r in issued)
        self.assertEqual(len(heights), len(set(heights)),
                         f"duplicate block heights: {heights}")
        # heights are consumed one at a time by the lock, but revokes also
        # consume heights, so only "all issued heights > start" and
        # "monotonic ordering" are guaranteed
        self.assertTrue(all(h > start_height for h in heights))
        self.assertGreaterEqual(bu.last_height(str(cs.CHAIN_DIR)),
                                max(heights))

        ok, problems = bu.verify_chain(str(cs.CHAIN_DIR))
        self.assertTrue(ok, f"chain does not replay: {problems[:3]}")

        # every block on disk must be readable and sequential
        final = bu.last_height(str(cs.CHAIN_DIR))
        for height in range(1, final + 1):
            block = bu.load_block(str(cs.CHAIN_DIR), height)
            self.assertEqual(block["height"], height)

        # the three anchors were revoked while writing was in full swing
        for anchor in anchors:
            self.assertEqual(cs.verify_hash(anchor)["verdict"], "REVOKED")

    def test_verdicts_settle_after_the_storm(self):
        """Every issued credential ends in a definite verdict, none in ERROR."""
        issued = [cs.issue(_doc(100 + i)) for i in range(4)]
        cs.revoke(issued[0]["hashed_document"], reason="settle")
        verdicts = {}
        for res in issued:
            verdicts[res["hashed_document"]] = cs.verify_hash(
                res["hashed_document"])["verdict"]
        self.assertEqual(verdicts[issued[0]["hashed_document"]], "REVOKED")
        for res in issued[1:]:
            self.assertEqual(verdicts[res["hashed_document"]], "VALID ON CHAIN")

    def test_revocation_index_agrees_with_the_chain(self):
        """The write-through index is a cache; the chain is the truth."""
        target = cs.issue(_doc(200))
        cs.revoke(target["hashed_document"], reason="index parity")
        records = cs.revoked_records()
        match = [r for r in records if r["hash"] == target["hashed_document"]]
        self.assertEqual(len(match), 1, "revocation missing from the replay")
        self.assertEqual(match[0]["reason"], "index parity")
        meta = cs.revoke_meta(target["hashed_document"])
        self.assertEqual(meta.get("reason"), "index parity")


if __name__ == "__main__":
    unittest.main()
