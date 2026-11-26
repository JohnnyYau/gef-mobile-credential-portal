"""Convert the product's copy from Simplified to Traditional (Hong Kong).

Only CJK runs are rewritten; HTML tags, JS identifiers, CSS and ASCII stay byte
for byte, so nothing structural can move. opencc s2hk does the bulk, then a
short override table fixes the handful of terms Hong Kong reads differently
(連結, 裡, 預設).

Idempotent: running it twice changes nothing the second time.

    python scripts/to_traditional.py --check     # report only
    python scripts/to_traditional.py --apply     # rewrite in place
"""

import argparse
import re
import sys
from pathlib import Path

import opencc

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ["static/**/*.html", "static/**/*.js"]

OVERRIDES = [
    ("鏈接", "連結"),
    ("裏", "裡"),
    ("默認", "預設"),
]

CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+")

_cc = opencc.OpenCC("s2hk")


def convert_run(match: re.Match) -> str:
    text = _cc.convert(match.group(0))
    for old, new in OVERRIDES:
        text = text.replace(old, new)
    return text


def convert_file(path: Path, apply: bool) -> int:
    raw = path.read_text(encoding="utf-8")
    new = CJK_RUN.sub(convert_run, raw)
    if new == raw:
        return 0
    changed = sum(1 for a, b in zip(raw, new) if a != b)
    if apply:
        path.write_text(new, encoding="utf-8", newline="")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    total = 0
    for pattern in TARGETS:
        for path in sorted(ROOT.glob(pattern)):
            if ".venv" in path.parts:
                continue
            n = convert_file(path, args.apply)
            if n:
                total += n
                print(f"{'rewrote' if args.apply else 'would change'} "
                      f"{path.relative_to(ROOT)}  ({n} chars)")
    print(f"{'changed' if args.apply else 'pending'}: {total} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
