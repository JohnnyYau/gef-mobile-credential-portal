"""public_log.py — anonymized verification log (post-Week-3 extra).

Disk-backed: every verification is appended to ``<chain-dir>/../public-log.jsonl``
so the public log survives restarts (the plan's "build trust" extra, now
persistent). The on-disk file holds hash prefixes only — never full documents.

Since batch U2 the disk work is delegated to ``repository`` (same jsonl layout,
or a ``log_entries`` table under the SQLite backend). The 50-entry window the
Log tab shows is kept here so callers see the same totals as before: the store
holds the durable history, this class clamps it to ``max_entries``.
"""

from pathlib import Path

from . import repository
from .config import CHAIN_DIR

MAX_ENTRIES = 50
MAX_FILE_LINES = 2000  # trim the jsonl when it exceeds this


def _log_path() -> Path:
    return CHAIN_DIR.parent / "public-log.jsonl"


class PublicLog:
    def __init__(self, max_entries=MAX_ENTRIES):
        self._max_entries = max_entries

    def record(self, hashed_document, verdict):
        repository.store("log").record(hashed_document, verdict)

    def recent(self, limit=MAX_ENTRIES):
        return repository.store("log").recent(min(limit, self._max_entries))

    def total(self):
        return min(repository.store("log").total(), self._max_entries)


verification_log = PublicLog()
