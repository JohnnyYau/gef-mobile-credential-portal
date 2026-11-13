#!/usr/bin/env python3
"""batch_verify.py — employer-pack CLI: verify a CSV of credential hashes
against a running portal and emit a results CSV (with a machine-readable
summary row). Any extra columns are passed through untouched.

Usage:
    python scripts/batch_verify.py --csv hashes.csv --out results.csv \\
        --api http://127.0.0.1:8000 [--api-key YOUR_API_KEY]

CSV format: one credential hash per row; the column name must be
`hashed_document` (or exactly `hash`). Example:

    hashed_document,applicant_id
    <hash>,A-001
    <hash>,A-002

Exit code: 0 when the API responded (regardless of per-row verdicts);
1 on network/auth/HTTP-level failure. When the portal cannot be reached the
tool still writes a results file so downstream pipelines get an explicit error.
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Allow running from the repo without installing: scripts/ -> portal root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HASH_COLUMN_NAMES = ("hashed_document", "hash")
EXTRA_OUTPUT_COLUMNS = (
    "hashed_document", "verdict", "chain_integrity", "signer_trusted",
    "on_chain_record", "hash_match", "signature_valid", "not_revoked",
    "receipt_id", "reason", "effective_at", "error",
)


def api_verify_batch(base_url: str, api_key: str | None,
                     hashes: list[str]) -> dict:
    url = base_url.rstrip("/") + "/api/verify/batch"
    body = json.dumps({"hashes": hashes}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="input CSV of hashes")
    parser.add_argument("--out", required=True, help="output results CSV")
    parser.add_argument("--api", default="http://127.0.0.1:8000",
                        help="portal base URL")
    parser.add_argument("--api-key", default=None,
                        help="public API key (Authorization: Bearer)")
    args = parser.parse_args()

    in_path = Path(args.csv)
    if not in_path.exists():
        print(f"error: input CSV not found: {in_path}", file=sys.stderr)
        return 1

    with open(in_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            print("error: input CSV has no header row", file=sys.stderr)
            return 1
        col = next((c for c in HASH_COLUMN_NAMES if c in reader.fieldnames), None)
        if col is None:
            print(f"error: expected a '{HASH_COLUMN_NAMES[0]}' or 'hash' column, "
                  f"got {reader.fieldnames}", file=sys.stderr)
            return 1
        rows = list(reader)

    hashes = [(r[col] or "").strip() for r in rows]
    try:
        result = api_verify_batch(args.api, args.api_key, hashes)
    except urllib.error.HTTPError as exc:
        _write_failure(args.out, rows, col, f"HTTP {exc.code}: {exc.read()[:200]!r}")
        print(f"error: API returned HTTP {exc.code}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        _write_failure(args.out, rows, col, f"cannot reach {args.api}: {exc}")
        print(f"error: cannot reach {args.api}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — anything else is a hard failure
        _write_failure(args.out, rows, col, f"unexpected: {exc}")
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out_rows = []
    for r, v in zip(rows, result.get("results", [])):
        out = {**{k: r.get(k, "") for k in r},
               **{k: v.get(k, "") for k in EXTRA_OUTPUT_COLUMNS}}
        out_rows.append(out)

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) +
                                list(EXTRA_OUTPUT_COLUMNS))
        writer.writeheader()
        writer.writerows(out_rows)
        # machine-readable summary as the last row (prefixed keys so it cannot
        # collide with passthrough columns)
        summary = result.get("summary", {})
        writer.writerow({"hashed_document": "SUMMARY",
                         "verdict": json.dumps(summary)})

    print(f"ok: wrote {len(out_rows)} rows + summary to {args.out}")
    print(f"summary: {json.dumps(summary, sort_keys=True)}")
    return 0


def _write_failure(out_path: str, rows: list[dict], col: str,
                   error: str) -> None:
    """Write an explicit error file instead of failing silently."""
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) +
                                list(EXTRA_OUTPUT_COLUMNS))
        writer.writeheader()
        for r in rows:
            writer.writerow({**r, "hashed_document": r.get(col, ""),
                             "verdict": "ERROR", "error": error})
    print(f"error: wrote failure rows to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
