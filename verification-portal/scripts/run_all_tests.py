"""Run the full test suite module-by-module in isolated subprocesses.

The test modules share global app state (chain dir, signer registry, log
files), so running them inside one unittest process causes ordering
collisions. This runner shells out to a fresh Python process per module —
the same isolation semantics each module was written for.

Usage:
    python scripts/run_all_tests.py                 # all modules
    python scripts/run_all_tests.py test_rag        # one module
    python scripts/run_all_tests.py --tier unit     # only one tier (batch U7.1)
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
sys.path.insert(0, str(ROOT))

MODULES = [
    "tests.test_api",
    "tests.test_hardening",
    "tests.test_features",
    "tests.test_extra2",
    "tests.test_employer_pack",
    "tests.test_public_mode",
    "tests.test_rag",
    "tests.test_person",
    "tests.test_restart_persistence",
    "tests.test_issue_batch",
    "tests.test_pdf_extract",
    "tests.test_custom",
    "tests.test_property_crypto",
    "tests.test_chain_integrity",
    "tests.test_disclosure",
    "tests.test_frontend",
    "tests.test_observability",
    "tests.test_fuzz",
    "tests.test_concurrency",
    "tests.test_storage_parity",
    "tests.test_backup",
    "tests.test_startup",
    "tests.test_optional_deps",
    "tests.test_chain_cache",
    "tests.test_receipts_store",
    "tests.test_audit_actor",
    "tests.test_key_at_rest",
    "tests.test_u13_hardening",
    "tests.test_u14_console",
    "tests.test_u15_diagnostics",
    "tests.test_u16_signers",
    "tests.test_u17_offline",
    "tests.test_u18_anchor",
    "tests.test_u19_diagnostics",
    "tests.test_u20_pin_update",
    "tests.test_u21_pdf_layout",
    "tests.test_u22_text_fit",
    "tests.test_u23_integrity_age",
    "tests.test_u24_proxy_trust",
]


def run_module(mod: str) -> bool:
    print(f"\n=== {mod} ===", flush=True)
    t0 = time.time()
    proc = subprocess.run(
        [PY, "-m", "unittest", mod, "-v"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    # unittest's TextTestRunner defaults to sys.stderr, so combine both
    out = proc.stdout + proc.stderr
    tail = "\n".join(out.splitlines()[-6:])
    ok = proc.returncode == 0 and "OK" in out[-2000:]
    print(f"--- {mod}: {'ok' if ok else 'FAILED'} ({time.time() - t0:.1f}s)")
    print(tail)
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="substring filter on module names")
    parser.add_argument("--tier", choices=("unit", "integration", "hardening"),
                        help="run only modules classified in this tier")
    args = parser.parse_args()

    from tests.tiers import TIERS, tier_of, unclassified

    missing = unclassified(MODULES)
    if missing:
        print("ERROR: modules with no tier in tests/tiers.py: " + ", ".join(missing))
        sys.exit(2)
    for module in MODULES:
        if tier_of(module) not in TIERS:      # registry typo guard
            print(f"ERROR: bad tier for {module}")
            sys.exit(2)

    mods = MODULES
    if args.names:
        mods = [m for m in mods if any(w in m for w in args.names)]
    if args.tier:
        mods = [m for m in mods if tier_of(m) == args.tier]
    if not mods:
        print("no module matched the filter")
        sys.exit(2)

    results = {m: run_module(m) for m in mods}
    print("\n==================== SUMMARY ====================")
    for m, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {m}")
    failed = [m for m, ok in results.items() if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} modules green")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
