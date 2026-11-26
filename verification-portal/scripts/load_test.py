"""load_test.py — concurrency + latency baseline for the demo deployment (U7.3).

Why a hand-rolled script instead of locust/k6: the project installs zero extra
dependencies for the demo, and the questions this needs to answer are narrow —
how many requests per second a single uvicorn worker sustains on the verification
surface, and where the latency tail sits. ``http.client`` + a thread pool covers
that in ~150 lines and adds nothing to requirements.

Usage (PowerShell):
    python scripts/load_test.py --base-url http://127.0.0.1:8022 --duration 8
    python scripts/load_test.py --hash <hashed_document> --concurrency 16

Exit code is 0 when the run stayed inside the thresholds given on the command
line (``--max-p95-ms``, ``--max-error-rate``), 1 otherwise — so it can gate a
demo rehearsal without a human reading the numbers.
"""

import argparse
import http.client
import json
import statistics
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

LOCK = threading.Lock()


def _one(url_parts, path: str, timeout: float,
         api_key: str | None = None) -> tuple[int, float]:
    """Single request; returns (status_code, latency_ms). Status 0 = transport error."""
    conn = http.client.HTTPConnection(url_parts.hostname, url_parts.port,
                                      timeout=timeout)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    started = time.perf_counter()
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        resp.read()
        return resp.status, (time.perf_counter() - started) * 1000
    except Exception:                             # noqa: BLE001 - counted as 0
        return 0, (time.perf_counter() - started) * 1000
    finally:
        conn.close()


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def run(args) -> dict:
    parts = urlparse(args.base_url)
    if not parts.hostname:
        raise SystemExit(f"bad --base-url: {args.base_url!r}")

    paths = ["/healthz", "/api/version", "/api/metrics"]
    if args.hash:
        paths.insert(0, f"/api/verify/{args.hash}")

    latencies: list[float] = []
    statuses: Counter = Counter()
    deadline = time.perf_counter() + args.duration
    sent = 0

    def worker(seed: int) -> None:
        nonlocal sent
        i = seed
        while time.perf_counter() < deadline:
            path = paths[i % len(paths)]
            i += 1
            code, ms = _one(parts, path, args.timeout, args.api_key)
            with LOCK:
                statuses[code] += 1
                latencies.append(ms)
                sent += 1

    threads = [threading.Thread(target=worker, args=(n,), daemon=True)
               for n in range(args.concurrency)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = max(time.perf_counter() - started, 1e-6)

    ok = statuses.get(200, 0)
    throttled = statuses.get(429, 0)
    # A 429 is the limiter doing its job, not a defect: it is reported as its
    # own number and excluded from the error rate, which then measures real
    # failures (5xx, transport errors, unexpected 4xx).
    errors = sent - ok - throttled
    report = {
        "base_url": args.base_url,
        "used_api_key": bool(args.api_key),
        "concurrency": args.concurrency,
        "duration_s": round(elapsed, 2),
        "requests": sent,
        "rps": round(sent / elapsed, 1),
        "ok": ok,
        "throttled_429": throttled,
        "error_rate": round(errors / sent, 4) if sent else 1.0,
        "statuses": dict(statuses),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else 0,
            "p90": round(_percentile(latencies, 90), 2),
            "p95": round(_percentile(latencies, 95), 2),
            "p99": round(_percentile(latencies, 99), 2),
            "max": round(max(latencies), 2) if latencies else 0,
        },
        "paths": paths,
        "host": args.base_url,
        "python": sys.version.split()[0],
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--hash", default=None,
                    help="hashed_document to include as /api/verify/... traffic")
    ap.add_argument("--api-key", default=None,
                    help="Bearer API key: per-key quota instead of per-IP")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--max-p95-ms", type=float, default=None)
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    report = run(args)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if report["ok"] == 0:
        print("FAIL: no successful request — is the server up?")
        return 1
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")

    failures = []
    if report["error_rate"] > args.max_error_rate:
        failures.append(f"error_rate {report['error_rate']} > {args.max_error_rate}")
    if args.max_p95_ms is not None:
        p95 = report["latency_ms"]["p95"]
        if p95 > args.max_p95_ms:
            failures.append(f"p95 {p95}ms > {args.max_p95_ms}ms")
    for line in failures:
        print("FAIL:", line)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
