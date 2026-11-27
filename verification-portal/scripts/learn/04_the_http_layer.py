"""Station 4 · the HTTP layer computes nothing

Run from verification-portal/:
    .venv\\Scripts\\python.exe scripts\\learn\\04_the_http_layer.py

What you should see:
  1. The whole handler for GET /api/verify/{hash}: 11 lines, no arithmetic
  2. The same verdict, obtained by calling the service directly (no HTTP)
  3. Which layer owns which decision
"""

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from app import blockchain_util, chain_service          # noqa: E402

MAIN = ROOT / "app" / "main.py"
FIRST, LAST = 996, 1006


def main():
    src = MAIN.read_text(encoding="utf-8").splitlines()

    print("=" * 78)
    print(f"1. app/main.py lines {FIRST}-{LAST} — the entire route")
    print("=" * 78)
    for no in range(FIRST, LAST + 1):
        print(f"  {no:>4}  {src[no - 1]}")

    print()
    print("  Lines that do mathematics: 0")
    print("  It validates the input, calls the service, adds a receipt id, logs, returns.")

    hashed = blockchain_util.load_block(str(ROOT / "data" / "demo-chain"), 1)["payload"]["HashedDocument"]

    print()
    print("=" * 78)
    print("2. Call the service directly — no HTTP, no browser, no server")
    print("=" * 78)
    t0 = time.perf_counter()
    result = chain_service.verify_hash(hashed)
    ms = (time.perf_counter() - t0) * 1000
    print(f"  chain_service.verify_hash({hashed[:16]}…) -> {ms:.0f} ms")
    print(f"  keys returned: {', '.join(sorted(result))}")
    print()
    print(f"  verdict          {result.get('verdict')}")
    for key in ("chain_integrity", "signer_trusted", "on_chain_record",
                "hash_match", "signature_valid", "not_revoked"):
        if key in result:
            print(f"  {key:<17}{result[key]}")

    print()
    print("=" * 78)
    print("3. Who decides what")
    print("=" * 78)
    rows = [
        ("main.py:996-1006", "route", "shape of input, token, then hand over"),
        ("chain_service.verify_hash", "service", "assemble the verdict dict"),
        ("blockchain_util.verify_document", "core", "the six checks"),
        ("crypto_util.verify_ds", "core", "is this signature real"),
        ("static/simple_verify.js", "front", "draw a card from the JSON"),
    ]
    for where, layer, does in rows:
        print(f"  {where:<36}{layer:<9}{does}")
    print("\n  → The chain is the only thing that knows the answer.")
    print("     Everything above it only carries the answer around.")


if __name__ == "__main__":
    main()

