"""Run the full test suite module-by-module in isolated subprocesses.

The test modules share global app state (chain dir, signer registry, log
files), so running them inside one unittest process causes ordering
collisions. This runner shells out to a fresh Python process per module —
the same isolation semantics each module was written for.

Usage:
    python scripts/run_all_tests.py            # all modules
    python scripts/run_all_tests.py test_rag   # one module
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

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
    wanted = sys.argv[1:]
    mods = [m for m in MODULES if not wanted or any(w in m for w in wanted)]
    results = {m: run_module(m) for m in mods}
    print("\n==================== SUMMARY ====================")
    for m, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {m}")
    failed = [m for m, ok in results.items() if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} modules green")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
