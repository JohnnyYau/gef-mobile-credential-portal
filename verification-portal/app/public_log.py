"""public_log.py — anonymized verification log (post-Week-3 extra).

Disk-backed: every verification is appended to ``<chain-dir>/../public-log.jsonl``
so the public log survives restarts (the plan's "build trust" extra, now
persistent). The on-disk file holds hash prefixes only — never full documents.
If the log file is unwritable (read-only FS, weird sandbox), the portal keeps
working in memory-only mode.
"""

import json
import os
import threading
import time
from collections import deque
from pathlib import Path

from .config import CHAIN_DIR

MAX_ENTRIES = 50
MAX_FILE_LINES = 2000  # trim the jsonl when it exceeds this


def _log_path() -> Path:
    return CHAIN_DIR.parent / "public-log.jsonl"


class PublicLog:
    def __init__(self, max_entries=MAX_ENTRIES):
        self._entries = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._path = _log_path()
        self._file = None
        self._load_existing()

    def _load_existing(self):
        try:
            if self._path.exists():
                lines = self._path.read_text(encoding="utf-8").splitlines()
                for line in lines[-MAX_FILE_LINES:]:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and "time" in rec:
                        self._entries.append(rec)
        except OSError:
            pass  # memory-only mode

    def record(self, hashed_document, verdict):
        rec = {
            "time": int(time.time()),
            "hash_prefix": (hashed_document or "")[:12],
            "verdict": verdict or "UNKNOWN",
        }
        with self._lock:
            self._entries.append(rec)
            self._append_disk(rec)

    def _append_disk(self, rec):
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # bounded file: rewrite with the tail when it grows too large
            if self._path.stat().st_size > 512 * 1024:
                tail = list(self._entries)[-MAX_FILE_LINES:]
                self._path.write_text(
                    "\n".join(json.dumps(r, ensure_ascii=False) for r in tail) + "\n",
                    encoding="utf-8",
                )
        except OSError:
            pass  # memory-only mode

    def recent(self, limit=MAX_ENTRIES):
        with self._lock:
            return list(self._entries)[-limit:]

    def total(self):
        with self._lock:
            return len(self._entries)


verification_log = PublicLog()
