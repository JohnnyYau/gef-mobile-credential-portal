"""U5.1 retrieval evaluation: recall@k, hit@1, MRR on the demo chain.

Runs with reranking off and on, prints both, and exits non-zero only if the
golden set itself is broken (a query whose expected id is not even in the
corpus). The numbers go into docs/U5.1_retrieval.md as the regression baseline.

Usage (from verification-portal):
    python scripts/rag_eval.py
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEMO = ROOT / "data" / "demo-chain"
os.environ.setdefault("CHAIN_DIR", str(DEMO))

from app import blockchain_util, rag_indexer  # noqa: E402
from app.config import CHAIN_DIR  # noqa: E402


def golden_set(chain):
    """Questions an employer actually asks, with the entry id that answers it."""
    info = blockchain_util.read_info(chain)
    height = blockchain_util.last_height(chain)
    raw_dir = Path(chain) / "rawjsondocs"
    docs = sorted(raw_dir.glob("*.json")) if raw_dir.is_dir() else []

    cases = [
        ("What is the current chain height?", f"block-{height:09d}"),
        ("Who are the trusted data signers on this chain?", "chain:info"),
        ("Which content hash algorithm does the chain use?", "chain:info"),
        ("Show the most recent block", f"block-{height:09d}"),
    ]
    if docs:
        first = docs[0]
        doc = json.loads(first.read_text(encoding="utf-8"))
        hashed = first.stem
        pp = doc.get("PersonalParticulars", {})
        cases.append((f"Is {pp.get('StudentID')} a valid credential?", f"credential:{hashed}"))
        cases.append((f"Credential of {pp.get('Surname')} {pp.get('GivenNames')}",
                      f"credential:{hashed}"))
        cases.append((f"Verify document hash {hashed}", f"credential:{hashed}"))
    else:
        cases.append(("Any credential on chain?", "chain:info"))

    cases.append(("Was anything revoked?", None))          # any block entry answers
    cases.append(("How many issuers signed the latest block?", f"block-{height:09d}"))
    cases.append(("Is the chain data intact?", "chain:info"))
    return [(q, exp) for q, exp in cases], info


def evaluate(index, cases, k=6, fetch=None, cut=None):
    """Metrics over ``cases``.

    ``fetch`` overrides how many candidates are retrieved, ``cut`` truncates to
    the first N results before scoring — that is how the 2k-window effect is
    isolated from the lexical reranking effect.
    """
    fetch = fetch or k
    cut = cut or k
    recall = 0
    rr_total = 0.0
    top1 = 0
    for query, expected in cases:
        results = index.search(query, k=fetch)[:cut]
        ids = [r["id"] for r in results]
        if expected is None:
            first_rank = next((n for n, i in enumerate(ids, 1)
                              if i.startswith("block-")), None)
        else:
            first_rank = ids.index(expected) + 1 if expected in ids else None
        recall += 1 if first_rank else 0
        rr_total += (1.0 / first_rank) if first_rank else 0.0
        top1 += 1 if first_rank == 1 else 0
    n = len(cases)
    return {"n": n,
            "recall_at_k": round(recall / n, 3),
            "hit_at_1": round(top1 / n, 3),
            "mrr": round(rr_total / n, 3)}


def main():
    cases, info = golden_set(str(CHAIN_DIR))
    print(f"chain={CHAIN_DIR} height={info.get('last_block_height')} queries={len(cases)}")

    configs = [
        ("rerank-off k=6", False, 6, 6),
        ("rerank-off window=12 cut=6", False, 12, 6),
        ("rerank-on window=12 cut=6", True, 12, 6),
    ]
    for label, rerank, fetch, cut in configs:
        rag_indexer.RERANK_ENABLED = rerank
        idx = rag_indexer.RagIndex()
        idx.ensure_ready()
        metrics = evaluate(idx, cases, fetch=fetch, cut=cut)
        print(f"{label}: recall@6={metrics['recall_at_k']} "
              f"hit@1={metrics['hit_at_1']} mrr={metrics['mrr']} "
              f"cache={idx.stats().get('cache')}")

    rag_indexer.RERANK_ENABLED = False
    missing = [q for q, e in cases
               if e is not None and e not in {r["id"] for r in
                                              rag_indexer.RagIndex().search(q, k=50)}]
    if missing:
        print("GOLDEN SET BROKEN (expected id not retrievable at k=50):")
        for q in missing:
            print("  -", q)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
