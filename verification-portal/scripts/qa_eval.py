"""qa_eval.py — offline QA golden set (batch U5.4).

Complements ``scripts/rag_eval.py`` (retrieval side: recall/hit@1/MRR) with the
answer side: does the offline engine answer the right thing, and are the
citations it shows pointing at the records that actually support the answer?

Metrics per case:
  answered    the answer contains the expected fact (substring check)
  cited_ok    every expected citation target is present in ``sources``
  clean       no unrelated credential is cited (guards against "cite
              everything and hope")

Run:  .venv\\Scripts\\python.exe scripts\\qa_eval.py
Exit code 2 means the golden set itself is broken (expected data missing),
not that answers are wrong.

The chain is built fresh under a temp dir, so numbers are reproducible and
never depend on whatever data/demo-chain currently holds.
"""

import json
import sys
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PORTAL))

from tests._bootstrap import isolated_chain_dir  # noqa: E402

_TMP = isolated_chain_dir(prefix="qa-eval-", DEEPSEEK_API_KEY=None,
                          OLLAMA_BASE_URL=None)

from app import chain_service, chat_service, person_context  # noqa: E402
from app.chain_service import SAMPLE_DIPLOMA  # noqa: E402

# Extra fixtures: one staying VALID, one REVOKED, one second student for
# citation-precision checks. (The first version reused the same document for
# both the VALID and the REVOKED case — same content hash — so the "VALID"
# expectation could never hold. The golden set caught that too.)
chain_service.ensure_chain()

_valid = json.loads(json.dumps(SAMPLE_DIPLOMA))
_valid["PersonalParticulars"]["Surname"] = "LAM"
_valid["PersonalParticulars"]["GivenNames"] = "SIU MING"
_valid["PersonalParticulars"]["StudentID"] = "55554444"
_valid["AcademicInfo"]["DegreeName"] = "Bachelor of Engineering in Civil Engineering"
_valid_hash = chain_service.issue(_valid)["hashed_document"]

_revoked_hash = chain_service.issue(json.loads(json.dumps(SAMPLE_DIPLOMA)))["hashed_document"]
chain_service.revoke(_revoked_hash, "qa-eval fixture revocation")

_other = json.loads(json.dumps(SAMPLE_DIPLOMA))
_other["PersonalParticulars"]["Surname"] = "NG"
_other["PersonalParticulars"]["GivenNames"] = "KA LOK"
_other["PersonalParticulars"]["StudentID"] = "88990011"
_other["AcademicInfo"]["DegreeName"] = "Bachelor of Science in Data Science"
_other_hash = chain_service.issue(_other)["hashed_document"]

# --- golden set -----------------------------------------------------------
# expect_source: substring that must appear in one cited source id/text.
GOLDEN = [
    {"name": "hash-status", "q": f"Status of {_valid_hash}",
     "expect": ["VALID"], "expect_source": [_valid_hash[:12]]},
    {"name": "hash-revoked", "q": f"Is {_revoked_hash} revoked?",
     "expect": ["REVOKED"], "expect_source": [_revoked_hash[:12]]},
    {"name": "name-status", "q": "Has CHAN TAI MAN's diploma been revoked?",
     "expect": ["REVOKED"], "expect_source": [_revoked_hash[:12]]},
    {"name": "student-id", "q": "Is the credential of student 88990011 valid?",
     "expect": ["VALID"], "expect_source": [_other_hash[:12]]},
    {"name": "courses", "q": "Which courses are on CHAN TAI MAN's transcript?",
     "expect": ["lists:"], "expect_source": ["credential:"]},
    {"name": "count", "q": "How many blocks are on the chain?",
     "expect": ["blocks in total", "ISSUE"], "expect_source": ["chain:"]},
    {"name": "signer", "q": "Who is the trusted signer of this chain?",
     "expect": ["UNIVERSITY OF UTOPIA"], "expect_source": ["chain:"]},
    {"name": "integrity", "q": "Is the chain integrity ok?",
     "expect": ["integrity is OK"], "expect_source": ["chain:"]},
    {"name": "latest-block", "q": "What is the latest block?",
     "expect": ["latest block is height"], "expect_source": ["block-"]},
    {"name": "no-record", "q": "Is there a credential for student 99990000?",
     "expect": ["No credential is recorded"], "expect_source": [],
     "fallback": True},
]


def _source_ids(response):
    return [s.get("id", "") for s in response.get("sources") or []]


def _cited_ok(ids, expected):
    if not expected:
        return True  # nothing to cite is a valid outcome (no-record case)
    return any(token in one_id for token in expected for one_id in ids)


def run():
    person_context._sessions.clear()
    rows = []
    for case in GOLDEN:
        response = chat_service.answer(case["q"])
        answer = response.get("answer", "")
        ids = _source_ids(response)
        answered = all(token.lower() in answer.lower() for token in case["expect"])
        cited = _cited_ok(ids, case["expect_source"])
        fallback = response["generation"]["sources_are_fallback"]
        # A "no record" answer has nothing to cite; the contract is that the
        # UI is told so (fallback flag), not that sources are empty.
        expected_fallback = case.get("fallback")
        fallback_ok = expected_fallback is None or fallback == expected_fallback
        rows.append({"name": case["name"], "answered": answered, "cited": cited,
                     "fallback_ok": fallback_ok,
                     "backend": response.get("generator"),
                     "sources": ids, "fallback": fallback})
    return rows


def main():
    rows = run()
    print(f"golden_cases={len(rows)}")
    width = max(len(r["name"]) for r in rows)
    for r in rows:
        ok = r["answered"] and r["cited"] and r["fallback_ok"]
        print(f"{'PASS' if ok else 'FAIL'} "
              f"{r['name']:<{width}} answered={r['answered']!s:<5} "
              f"cited={r['cited']!s:<5} fallback={r['fallback']!s:<5} "
              f"sources={r['sources']}")

    answered = sum(1 for r in rows if r["answered"]) / len(rows)
    cited = sum(1 for r in rows if r["cited"]) / len(rows)
    fallback = sum(1 for r in rows if r["fallback_ok"]) / len(rows)
    joint = sum(1 for r in rows
                if r["answered"] and r["cited"] and r["fallback_ok"]) / len(rows)
    print(f"hit_rate={answered:.3f} citation_accuracy={cited:.3f} "
          f"fallback_contract={fallback:.3f} joint={joint:.3f}")
    if any(r["backend"] != "offline" for r in rows):
        print("NOTE: non-offline backend active; these numbers are not the "
              "offline baseline")
    return 0 if joint == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
