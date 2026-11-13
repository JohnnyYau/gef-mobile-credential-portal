"""anomaly.py — signer velocity watch (post-Week-3 extra, upgraded).

Two detectors, auto-selected:
1. ``isolation_forest`` — scikit-learn IsolationForest over each signer's
   hourly issue counts (the plan's "IsolationForest + chart" extra). Used when
   sklearn is importable and there are enough points to fit.
2. ``rule_based`` — the deterministic threshold fallback (count >=
   ANOMALY_ISSUE_PER_HOUR) used when sklearn is missing or the sample is tiny,
   so the endpoint never breaks and is fully reproducible in tests.

Flags are merged: a flagged hour carries the reason(s) that fired.
"""

import collections
import time

from . import blockchain_util
from .config import ANOMALY_ISSUE_PER_HOUR


def _signer_name(chain_addr, fingerprint):
    try:
        info = blockchain_util.read_info(chain_addr)
    except blockchain_util.ChainDataError:
        return (fingerprint or "unknown")[:16]
    for s in info.get("trusted_signers", []):
        if s.get("sha256fgpt") == fingerprint:
            return s.get("name") or (fingerprint or "")[:16]
    return (fingerprint or "unknown")[:16]


def _rule_flags(counts, last_height):
    """Threshold flags: >= ANOMALY_ISSUE_PER_HOUR issues in one hour."""
    flags = []
    for (key, hour), count in sorted(counts.items()):
        if count >= ANOMALY_ISSUE_PER_HOUR:
            flags.append({
                "signer": key,
                "hour_start": hour * 3600,
                "credential_count": count,
                "threshold": ANOMALY_ISSUE_PER_HOUR,
                "severity": "high" if count >= 3 * ANOMALY_ISSUE_PER_HOUR else "mild",
                "last_height": last_height[(key, hour)],
                "reasons": ["rule"],
            })
    return flags


def _isolation_flags(counts, last_height):
    """IsolationForest over hourly issue counts.

    Fits one forest per signer on their nonzero hourly counts; points predicted
    as outliers are flagged. ``n_estimators`` is kept low so a demo chain (a
    few hundred blocks) fits in well under a second.
    """
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return None

    flags = []
    for key in {k for (k, _h) in counts}:
        series = sorted((hour, counts[(key, hour)]) for (k, hour) in counts if k == key)
        values = [c for _h, c in series]
        if len(values) < 6:
            continue  # too few points for a meaningful fit
        X = [[float(v)] for v in values]
        model = IsolationForest(n_estimators=64, contamination=0.15,
                                random_state=0, n_jobs=1)
        pred = model.fit_predict(X)  # -1 = anomaly
        for (hour, _c), p in zip(series, pred):
            if p == -1:
                flags.append({
                    "signer": key,
                    "hour_start": hour * 3600,
                    "credential_count": counts[(key, hour)],
                    "threshold": ANOMALY_ISSUE_PER_HOUR,
                    "severity": "mild",
                    "last_height": last_height[(key, hour)],
                    "reasons": ["isolation_forest"],
                })
    return flags


def _merge_flags(*groups):
    """Merge flag lists keyed by (signer, hour_start), union the reasons."""
    merged = {}
    for group in groups or []:
        for flag in group:
            k = (flag["signer"], flag["hour_start"])
            if k not in merged:
                merged[k] = dict(flag)
            else:
                merged[k]["reasons"] = sorted(set(merged[k]["reasons"]) | set(flag["reasons"]))
                merged[k]["credential_count"] = max(
                    merged[k]["credential_count"], flag["credential_count"])
                merged[k]["last_height"] = max(
                    merged[k]["last_height"], flag["last_height"])
    return sorted(merged.values(), key=lambda f: -f["credential_count"])


def detect(chain_addr):
    info = blockchain_util.read_info(chain_addr)
    last = int(info.get("last_block_height", -1))

    counts = collections.Counter()      # (signer, hour) -> n
    last_height = {}                    # (signer, hour) -> block height
    for height in range(1, last + 1):
        block = blockchain_util.load_block(chain_addr, height)
        payload = block.get("payload", {})
        if payload.get("action") != "ISSUE":
            continue
        ds = block.get("DataSignatureInfo", [])
        fp = ds[0].get("DSsha256fgpt", "") if ds else ""
        key = _signer_name(chain_addr, fp)
        ts_ns = int(block.get("timestamp", 0)) or 0
        hour = ts_ns // 1_000_000_000 // 3600  # chain stores ns timestamps
        counts[(key, hour)] += 1
        last_height[(key, hour)] = height

    rule_flags = _rule_flags(counts, last_height)
    iso_flags = _isolation_flags(counts, last_height)
    method = "isolation_forest" if iso_flags is not None else "rule_based"
    anomalies = _merge_flags(rule_flags, iso_flags or [])

    # hourly histogram for the chart (last 24 hours, all signers)
    now_hour = int(time.time()) // 3600
    hist = collections.Counter()
    for (key, hour), count in counts.items():
        if now_hour - 24 <= hour <= now_hour:
            hist[hour] += count
    hourly_issues = [
        {"hour": h, "count": hist.get(h, 0)}
        for h in range(now_hour - 23, now_hour + 1)
    ]

    return {
        "window_hours": 1,
        "threshold": ANOMALY_ISSUE_PER_HOUR,
        "method": method,
        "anomalies": anomalies,
        "hourly_issues": hourly_issues,
    }
