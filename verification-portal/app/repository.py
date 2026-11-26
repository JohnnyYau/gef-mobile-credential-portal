"""repository.py — storage abstraction layer (internal, batch U2.1).

Five stores, each with two interchangeable implementations:

    ApiKeyStore          api_keys        (kid -> digest/name/timestamps/revoked)
    ReceiptStore         receipts        (receipt_id -> hash/verdict/endpoint)
    LogStore             log_entries     (anonymised verification log)
    NotificationStore    notifications   (notifier audit trail)
    RevocationIndexStore revocation_index(hash -> issued height / revoked flag)

``Json*`` implementations read and write the *existing* files in the *existing*
formats (``data/apikeys.json``, ``data/receipts.json``,
``<chain-dir>/../public-log.jsonl``, ``<chain-dir>/../notifications.jsonl``), so
switching the backend on changes nothing observable to callers.

``Sqlite*`` implementations put the same records in one SQLite file (stdlib
``sqlite3``, zero new dependencies). Writes serialise on a per-store lock and
each operation uses its own short-lived connection, so a crash cannot leave a
half-written row and multiple threads do not share a connection object.

``migrate_json_to_sqlite()`` imports the JSON side once; a ``meta`` row
(``migration_version``) makes repeat runs no-ops.

This layer is deliberately **not wired into the endpoints yet**: per the U2
risk note we switch reads first, then writes. Endpoint modules keep their
current code paths until U2.2 lands.
"""

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from . import config as cfg

MIGRATION_VERSION = "1"
_KEY_DIGEST_SALT = "gef26-apikey:"  # unchanged: existing digests stay valid

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        name TEXT,
        created_at REAL,
        last_used_at REAL,
        revoked INTEGER NOT NULL DEFAULT 0,
        hash TEXT NOT NULL,
        expires_at REAL,
        use_count INTEGER NOT NULL DEFAULT 0,
        revoke_reason TEXT,
        replaced_by TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(hash)",
    """
    CREATE TABLE IF NOT EXISTS receipts (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id TEXT NOT NULL UNIQUE,
        hashed_document TEXT,
        verdict TEXT,
        verified_at REAL,
        endpoint TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_receipts_id ON receipts(receipt_id)",
    """
    CREATE TABLE IF NOT EXISTS log_entries (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        hash_prefix TEXT,
        verdict TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notifications (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        to_addr TEXT,
        subject TEXT,
        status TEXT,
        detail TEXT,
        url TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS revocation_index (
        hashed_document TEXT PRIMARY KEY,
        issued_height INTEGER,
        revoked INTEGER NOT NULL DEFAULT 0,
        reason TEXT,
        effective_at REAL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        time INTEGER NOT NULL,
        action TEXT NOT NULL,
        subject TEXT,
        outcome TEXT,
        detail TEXT,
        actor TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action)",
)


def key_digest(key: str) -> str:
    """Salt + SHA-256 digest of an API key (same scheme as the JSON store)."""
    return hashlib.sha256((_KEY_DIGEST_SALT + key).encode("utf-8")).hexdigest()


def _expiry_from(created: float, expires_in_days: int | None) -> float | None:
    """Absolute expiry timestamp, or None for a key that never expires."""
    if not expires_in_days or expires_in_days <= 0:
        return None
    return created + float(expires_in_days) * 86400.0


def _is_expired(expires_at: float | None) -> bool:
    return expires_at is not None and time.time() >= float(expires_at)


# --------------------------------------------------------------------------
# Interfaces
# --------------------------------------------------------------------------


class ApiKeyStore(Protocol):
    def create_key(self, name: str, expires_in_days: int | None = None) -> dict: ...
    def list_keys(self) -> list: ...
    def revoke_key(self, kid: str, reason: str | None = None) -> bool: ...
    def rotate_key(self, kid: str, expires_in_days: int | None = None) -> dict | None: ...
    def validate_key(self, key: str) -> dict | None: ...


class ReceiptStore(Protocol):
    def register(self, hashed_document: str, verdict: str,
                 verified_at: float, endpoint: str) -> str: ...
    def get(self, receipt_id: str) -> dict | None: ...


class LogStore(Protocol):
    def record(self, hashed_document: str, verdict: str) -> dict: ...
    def recent(self, limit: int) -> list: ...
    def total(self) -> int: ...


class NotificationStore(Protocol):
    def record(self, to: str, subject: str, status: str, detail: str,
               url: str | None = None) -> dict: ...
    def recent(self, limit: int) -> list: ...


class RevocationIndexStore(Protocol):
    def upsert(self, hashed_document: str, issued_height: int | None,
               revoked: bool, reason: str | None = None,
               effective_at: float | None = None) -> None: ...
    def get(self, hashed_document: str) -> dict | None: ...
    def all(self) -> list: ...


class AuditStore(Protocol):
    """Administrative audit trail — separate from the anonymised public log."""

    def record(self, action: str, subject: str | None = None,
               outcome: str = "ok", detail: str | None = None) -> dict: ...
    def recent(self, limit: int = 50) -> list: ...


# --------------------------------------------------------------------------
# JSON implementations (existing on-disk formats, unchanged)
# --------------------------------------------------------------------------


def _json_read(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _atomic_write(path: Path, payload: Any, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


class JsonApiKeyStore:
    def __init__(self, path: Path | None = None):
        self._path = path or (cfg.BASE_DIR / "data" / "apikeys.json")
        self._lock = threading.Lock()

    def _load(self) -> dict:
        data = _json_read(self._path, {})
        return data if isinstance(data, dict) else {}

    def create_key(self, name: str, expires_in_days: int | None = None) -> dict:
        import secrets

        key = secrets.token_urlsafe(32)
        kid = secrets.token_hex(3)
        created = time.time()
        expires = _expiry_from(created, expires_in_days)
        with self._lock:
            store = self._load()
            store[kid] = {
                "name": (name or "unnamed")[:80],
                "created_at": created,
                "last_used_at": None,
                "revoked": False,
                "hash": key_digest(key),
                "expires_at": expires,
                "use_count": 0,
                "revoke_reason": None,
                "replaced_by": None,
            }
            _atomic_write(self._path, store, indent=1)
        return {"id": kid, "name": store[kid]["name"], "key": key,
                "created_at": created, "expires_at": expires}

    def list_keys(self) -> list:
        with self._lock:
            store = self._load()
            return [{
                "id": kid,
                "name": rec.get("name"),
                "created_at": rec.get("created_at"),
                "last_used_at": rec.get("last_used_at"),
                "revoked": bool(rec.get("revoked")),
                "expires_at": rec.get("expires_at"),
                "use_count": int(rec.get("use_count") or 0),
                "revoke_reason": rec.get("revoke_reason"),
                "replaced_by": rec.get("replaced_by"),
            } for kid, rec in sorted(store.items())]

    def revoke_key(self, kid: str, reason: str | None = None) -> bool:
        with self._lock:
            store = self._load()
            if kid not in store:
                return False
            store[kid]["revoked"] = True
            if reason:
                store[kid]["revoke_reason"] = str(reason)[:120]
            _atomic_write(self._path, store, indent=1)
            return True

    def rotate_key(self, kid: str, expires_in_days: int | None = None) -> dict | None:
        """Replace a live key: revoke the old one, hand back a fresh secret."""
        with self._lock:
            store = self._load()
            if kid not in store or store[kid].get("revoked"):
                return None
            new = self._create_in(store, store[kid].get("name") or "unnamed",
                                 expires_in_days)
            store[kid]["revoked"] = True
            store[kid]["revoke_reason"] = "rotated"
            store[kid]["replaced_by"] = new["id"]
            _atomic_write(self._path, store, indent=1)
            return new

    def _create_in(self, store: dict, name: str,
                   expires_in_days: int | None) -> dict:
        import secrets

        key = secrets.token_urlsafe(32)
        kid = secrets.token_hex(3)
        created = time.time()
        expires = _expiry_from(created, expires_in_days)
        store[kid] = {
            "name": (name or "unnamed")[:80],
            "created_at": created,
            "last_used_at": None,
            "revoked": False,
            "hash": key_digest(key),
            "expires_at": expires,
            "use_count": 0,
            "revoke_reason": None,
            "replaced_by": None,
        }
        return {"id": kid, "name": store[kid]["name"], "key": key,
                "created_at": created, "expires_at": expires}

    def validate_key(self, key: str) -> dict | None:
        if not key:
            return None
        digest = key_digest(key)
        with self._lock:
            store = self._load()
            for kid, rec in store.items():
                if rec.get("hash") == digest:
                    if rec.get("revoked"):
                        return None
                    if _is_expired(rec.get("expires_at")):
                        return None
                    rec["last_used_at"] = time.time()
                    rec["use_count"] = int(rec.get("use_count") or 0) + 1
                    _atomic_write(self._path, store, indent=1)
                    return {"id": kid, "use_count": rec["use_count"]}
            return None


def _read_receipts(path: Path) -> list:
    """Read a receipts file in either supported layout.

    U9-A moved this store from "rewrite the whole JSON array per verify" to
    append-only lines: the old code parsed + re-encoded every receipt on every
    verification, i.e. O(n) per request, which at the 5000 cap is a ~370 ms
    write behind every click. Both layouts are read here — an existing
    ``receipts.json`` array (list) is migrated to lines on the next write.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.strip():
        return []
    if text.lstrip().startswith("["):
        try:
            data = json.loads(text)
        except ValueError:
            return []
        return data if isinstance(data, list) else []
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue                       # a torn tail line, not the whole file
        if isinstance(record, dict):
            records.append(record)
    return records


def _write_receipts_lines(path: Path, records: list) -> None:
    """Compact the store: one JSON object per line, atomic via .tmp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
    os.replace(tmp, path)


def _append_receipt_line(path: Path, record: dict) -> None:
    """Append one receipt in O(1); no read, no full rewrite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        fh.write("\n")


class JsonReceiptStore:
    def __init__(self, path: Path | None = None, cap: int | None = None):
        self._path = path or (cfg.BASE_DIR / "data" / "receipts.json")
        self._cap = cap if cap is not None else cfg.RECEIPT_REGISTRY_CAP
        self._lock = threading.Lock()
        self._cache: list | None = None
        self._signature: tuple | None = None

    def _file_signature(self) -> tuple | None:
        try:
            stat = self._path.stat()
        except OSError:
            return None
        return (stat.st_size, stat.st_mtime_ns)

    def _load(self) -> list:
        """Cached read; invalidated by size/mtime so external edits still show."""
        signature = self._file_signature()
        if self._cache is not None and signature is not None \
                and signature == self._signature:
            return list(self._cache)
        records = _read_receipts(self._path)
        self._cache = records
        self._signature = signature
        return list(records)

    def register(self, hashed_document: str, verdict: str,
                 verified_at: float, endpoint: str) -> str:
        import secrets

        rid = f"RCP-{int(verified_at):x}-{secrets.token_hex(2).upper()}"
        record = {
            "receipt_id": rid,
            "hashed_document": hashed_document,
            "verdict": verdict,
            "verified_at": verified_at,
            "endpoint": endpoint,
        }
        with self._lock:
            cached = [] if self._cache is None else self._cache
            if self._signature is None:
                # First write after a restart (or a legacy array file): rebuild
                # the cache from disk once, then compact to line format so the
                # next append is a single write.
                cached = _read_receipts(self._path)
                cached.append(record)
                if len(cached) > self._cap:
                    cached = cached[-self._cap:]
                _write_receipts_lines(self._path, cached)
            else:
                cached = list(cached) + [record]
                # Compact with slack, not at the exact cap: trimming on every
                # append once the file reached the cap turned the O(1) append
                # back into a full rewrite per request (measured 30 ms at 5000
                # receipts, vs 0.1 ms with slack).
                slack = max(8, self._cap // 20)
                if len(cached) > self._cap + slack:
                    cached = cached[-self._cap:]
                    _write_receipts_lines(self._path, cached)
                else:
                    _append_receipt_line(self._path, record)
            self._cache = cached
            self._signature = self._file_signature()
        return rid

    def get(self, receipt_id: str) -> dict | None:
        with self._lock:
            for rec in self._load():
                if rec.get("receipt_id") == receipt_id:
                    return rec
            return None


class JsonLogStore:
    """Append-only jsonl with an in-memory tail, sized like the live log."""

    def __init__(self, path: Path | None = None, memory: int = 50,
                 max_lines: int = 2000):
        self._path = path or (cfg.CHAIN_DIR.parent / "public-log.jsonl")
        self._memory = memory
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._entries: list = []
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                lines = self._path.read_text(encoding="utf-8").splitlines()
                for line in lines[-self._max_lines:]:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and "time" in rec:
                        self._entries.append(rec)
        except OSError:
            pass  # memory-only mode

    def record(self, hashed_document: str, verdict: str) -> dict:
        rec = {
            "time": int(time.time()),
            "hash_prefix": (hashed_document or "")[:12],
            "verdict": verdict or "UNKNOWN",
        }
        with self._lock:
            self._entries.append(rec)
            if len(self._entries) > self._max_lines:
                self._entries = self._entries[-self._max_lines:]
            try:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError:
                pass  # memory-only mode
        return rec

    def recent(self, limit: int) -> list:
        with self._lock:
            return list(self._entries)[-limit:]

    def total(self) -> int:
        with self._lock:
            return len(self._entries)


class JsonNotificationStore:
    def __init__(self, path: Path | None = None):
        self._path = path or (cfg.CHAIN_DIR.parent / "notifications.jsonl")
        self._lock = threading.Lock()

    def record(self, to: str, subject: str, status: str, detail: str,
               url: str | None = None) -> dict:
        rec: dict[str, Any] = {
            "time": int(time.time()),
            "to": to,
            "subject": subject,
            "status": status,
            "detail": detail,
        }
        if url:
            rec["url"] = url
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return rec

    def recent(self, limit: int) -> list:
        out: list = []
        with self._lock:
            try:
                if self._path.exists():
                    lines = self._path.read_text(encoding="utf-8").splitlines()[-limit:]
                    for line in lines:
                        try:
                            out.append(json.loads(line))
                        except ValueError:
                            continue
            except OSError:
                pass
        return out


class JsonRevocationIndexStore:
    """Side-file index (no records yet -> empty index, never an error)."""

    def __init__(self, path: Path | None = None):
        self._path = path or (cfg.BASE_DIR / "data" / "revocation-index.json")
        self._lock = threading.Lock()

    def _load(self) -> dict:
        data = _json_read(self._path, {})
        return data if isinstance(data, dict) else {}

    def upsert(self, hashed_document: str, issued_height: int | None,
               revoked: bool, reason: str | None = None,
               effective_at: float | None = None) -> None:
        with self._lock:
            store = self._load()
            store[hashed_document] = {
                "hashed_document": hashed_document,
                "issued_height": issued_height,
                "revoked": bool(revoked),
                "reason": reason,
                "effective_at": effective_at,
                "updated_at": time.time(),
            }
            _atomic_write(self._path, store, indent=1)

    def get(self, hashed_document: str) -> dict | None:
        with self._lock:
            return self._load().get(hashed_document)

    def all(self) -> list:
        with self._lock:
            return sorted(self._load().values(),
                          key=lambda r: r["hashed_document"])


class JsonAuditStore:
    """Append-only jsonl: ``data/audit-log.jsonl``."""

    def __init__(self, path: Path | None = None, max_lines: int = 2000):
        self._path = path or (cfg.BASE_DIR / "data" / "audit-log.jsonl")
        self._max_lines = max_lines
        self._lock = threading.Lock()

    def record(self, action: str, subject: str | None = None,
               outcome: str = "ok", detail: str | None = None) -> dict:
        from .audit import current_actor  # local import: audit imports us

        rec: dict[str, Any] = {
            "time": int(time.time()),
            "action": action,
            "subject": subject,
            "outcome": outcome,
            "actor": current_actor(),
        }
        if detail:
            rec["detail"] = str(detail)[:200]
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError:
                pass  # audit must never break the request
        return rec

    def recent(self, limit: int = 50) -> list:
        out: list = []
        with self._lock:
            try:
                if self._path.exists():
                    for line in self._path.read_text(
                            encoding="utf-8").splitlines()[-self._max_lines:]:
                        try:
                            out.append(json.loads(line))
                        except ValueError:
                            continue
            except OSError:
                pass
        return out[-limit:]


# --------------------------------------------------------------------------
# SQLite implementations
# --------------------------------------------------------------------------

# Columns added after the initial schema. Existing databases predate them, so
# the backend adds whatever is missing on boot (idempotent, additive only).
_API_KEY_LIFECYCLE_COLUMNS = (
    ("expires_at", "REAL"),
    ("use_count", "INTEGER NOT NULL DEFAULT 0"),
    ("revoke_reason", "TEXT"),
    ("replaced_by", "TEXT"),
)


def _ensure_api_key_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(api_keys)")}
    for name, decl in _API_KEY_LIFECYCLE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE api_keys ADD COLUMN {name} {decl}")


def _ensure_audit_columns(conn: sqlite3.Connection) -> None:
    """U9-B: an audit row written before this batch has no operator."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(audit_events)")}
    if "actor" not in existing:
        conn.execute("ALTER TABLE audit_events ADD COLUMN actor TEXT")


class SqliteBackend:
    """Owns the database path, schema creation and connection lifecycle."""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = str(path or cfg.SQLITE_PATH)
        self._init_lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def ensure_schema(self) -> None:
        if self._ready:
            return
        with self._init_lock:
            if self._ready:
                return
            conn = self._connect()
            try:
                for stmt in _SCHEMA:
                    conn.execute(stmt)
                _ensure_api_key_columns(conn)
                _ensure_audit_columns(conn)
                conn.commit()
            finally:
                conn.close()
            self._ready = True

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        self.ensure_schema()
        conn = self._connect()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur
        finally:
            conn.close()

    def query(self, sql: str, params: tuple = ()) -> list:
        self.ensure_schema()
        conn = self._connect()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            # ``with sqlite3.connect(...)`` only commits/rolls back — it does
            # *not* close. Leaking one handle per query exhausted the pool
            # under batch verify (and locked the file on Windows).
            conn.close()

    def close(self) -> None:
        """No persistent handle is held between calls (U8.2 shutdown seam).

        Kept as an explicit no-op so ``Repository.close()`` has one uniform
        protocol across backends; a pooled implementation overrides it.
        """


class SqliteApiKeyStore:
    def __init__(self, backend: SqliteBackend):
        self._db = backend
        self._lock = threading.Lock()

    def create_key(self, name: str, expires_in_days: int | None = None) -> dict:
        import secrets

        key = secrets.token_urlsafe(32)
        kid = secrets.token_hex(3)
        created = time.time()
        expires = _expiry_from(created, expires_in_days)
        name_clean = (name or "unnamed")[:80]
        with self._lock:
            self._db.execute(
                "INSERT INTO api_keys (id, name, created_at, last_used_at,"
                " revoked, hash, expires_at, use_count) VALUES"
                " (?, ?, ?, NULL, 0, ?, ?, 0)",
                (kid, name_clean, created, key_digest(key), expires),
            )
        return {"id": kid, "name": name_clean, "key": key,
                "created_at": created, "expires_at": expires}

    def list_keys(self) -> list:
        rows = self._db.query(
            "SELECT id, name, created_at, last_used_at, revoked, expires_at,"
            " use_count, revoke_reason, replaced_by FROM api_keys ORDER BY id")
        return [{
            "id": r["id"],
            "name": r["name"],
            "created_at": r["created_at"],
            "last_used_at": r["last_used_at"],
            "revoked": bool(r["revoked"]),
            "expires_at": r["expires_at"],
            "use_count": int(r["use_count"] or 0),
            "revoke_reason": r["revoke_reason"],
            "replaced_by": r["replaced_by"],
        } for r in rows]

    def revoke_key(self, kid: str, reason: str | None = None) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE api_keys SET revoked = 1, revoke_reason = ?"
                " WHERE id = ?",
                (str(reason)[:120] if reason else None, kid))
            return cur.rowcount > 0

    def rotate_key(self, kid: str, expires_in_days: int | None = None) -> dict | None:
        rows = self._db.query(
            "SELECT name, revoked FROM api_keys WHERE id = ?", (kid,))
        if not rows or rows[0]["revoked"]:
            return None
        new = self.create_key(rows[0]["name"] or "unnamed", expires_in_days)
        with self._lock:
            self._db.execute(
                "UPDATE api_keys SET revoked = 1, revoke_reason = 'rotated',"
                " replaced_by = ? WHERE id = ?", (new["id"], kid))
        return new

    def validate_key(self, key: str) -> dict | None:
        if not key:
            return None
        rows = self._db.query(
            "SELECT id, revoked, expires_at, use_count FROM api_keys"
            " WHERE hash = ?", (key_digest(key),))
        if not rows:
            return None
        row = rows[0]
        if row["revoked"] or _is_expired(row["expires_at"]):
            return None
        count = int(row["use_count"] or 0) + 1
        with self._lock:
            self._db.execute(
                "UPDATE api_keys SET last_used_at = ?, use_count = ?"
                " WHERE id = ?", (time.time(), count, row["id"]))
        return {"id": row["id"], "use_count": count}


class SqliteReceiptStore:
    def __init__(self, backend: SqliteBackend, cap: int | None = None):
        self._db = backend
        self._cap = cap if cap is not None else cfg.RECEIPT_REGISTRY_CAP
        self._lock = threading.Lock()

    def register(self, hashed_document: str, verdict: str,
                 verified_at: float, endpoint: str) -> str:
        import secrets

        rid = f"RCP-{int(verified_at):x}-{secrets.token_hex(2).upper()}"
        with self._lock:
            self._db.execute(
                "INSERT INTO receipts (receipt_id, hashed_document, verdict,"
                " verified_at, endpoint) VALUES (?, ?, ?, ?, ?)",
                (rid, hashed_document, verdict, verified_at, endpoint),
            )
            self._db.execute(
                "DELETE FROM receipts WHERE seq <= ("
                " SELECT COALESCE(MAX(seq), 0) - ? FROM receipts)",
                (self._cap,),
            )
        return rid

    def get(self, receipt_id: str) -> dict | None:
        rows = self._db.query(
            "SELECT receipt_id, hashed_document, verdict, verified_at, endpoint"
            " FROM receipts WHERE receipt_id = ?", (receipt_id,))
        return dict(rows[0]) if rows else None


class SqliteLogStore:
    def __init__(self, backend: SqliteBackend, memory: int = 50):
        self._db = backend
        self._memory = memory
        self._lock = threading.Lock()

    def record(self, hashed_document: str, verdict: str) -> dict:
        rec = {
            "time": int(time.time()),
            "hash_prefix": (hashed_document or "")[:12],
            "verdict": verdict or "UNKNOWN",
        }
        with self._lock:
            self._db.execute(
                "INSERT INTO log_entries (time, hash_prefix, verdict)"
                " VALUES (?, ?, ?)",
                (rec["time"], rec["hash_prefix"], rec["verdict"]),
            )
        return rec

    def recent(self, limit: int) -> list:
        rows = self._db.query(
            "SELECT time, hash_prefix, verdict FROM log_entries"
            " ORDER BY seq DESC LIMIT ?", (limit,))
        return [dict(r) for r in reversed(rows)]

    def total(self) -> int:
        rows = self._db.query("SELECT COUNT(*) AS n FROM log_entries")
        return int(rows[0]["n"]) if rows else 0


class SqliteNotificationStore:
    def __init__(self, backend: SqliteBackend):
        self._db = backend
        self._lock = threading.Lock()

    def record(self, to: str, subject: str, status: str, detail: str,
               url: str | None = None) -> dict:
        rec: dict[str, Any] = {
            "time": int(time.time()),
            "to": to,
            "subject": subject,
            "status": status,
            "detail": detail,
        }
        if url:
            rec["url"] = url
        with self._lock:
            self._db.execute(
                "INSERT INTO notifications (time, to_addr, subject, status,"
                " detail, url) VALUES (?, ?, ?, ?, ?, ?)",
                (rec["time"], to, subject, status, detail, url),
            )
        return rec

    def recent(self, limit: int) -> list:
        rows = self._db.query(
            "SELECT time, to_addr, subject, status, detail, url FROM notifications"
            " ORDER BY seq DESC LIMIT ?", (limit,))
        out = []
        for r in reversed(rows):
            item = {
                "time": r["time"],
                "to": r["to_addr"],
                "subject": r["subject"],
                "status": r["status"],
                "detail": r["detail"],
            }
            if r["url"]:
                item["url"] = r["url"]
            out.append(item)
        return out


class SqliteRevocationIndexStore:
    def __init__(self, backend: SqliteBackend):
        self._db = backend
        self._lock = threading.Lock()

    def upsert(self, hashed_document: str, issued_height: int | None,
               revoked: bool, reason: str | None = None,
               effective_at: float | None = None) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO revocation_index (hashed_document, issued_height,"
                " revoked, reason, effective_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(hashed_document) DO UPDATE SET"
                " issued_height=excluded.issued_height, revoked=excluded.revoked,"
                " reason=excluded.reason, effective_at=excluded.effective_at,"
                " updated_at=excluded.updated_at",
                (hashed_document, issued_height, 1 if revoked else 0,
                 reason, effective_at, time.time()),
            )

    def get(self, hashed_document: str) -> dict | None:
        rows = self._db.query(
            "SELECT hashed_document, issued_height, revoked, reason, effective_at,"
            " updated_at FROM revocation_index WHERE hashed_document = ?",
            (hashed_document,))
        if not rows:
            return None
        rec = dict(rows[0])
        rec["revoked"] = bool(rec["revoked"])
        return rec

    def all(self) -> list:
        rows = self._db.query(
            "SELECT hashed_document, issued_height, revoked, reason, effective_at,"
            " updated_at FROM revocation_index ORDER BY hashed_document")
        out = []
        for r in rows:
            rec = dict(r)
            rec["revoked"] = bool(rec["revoked"])
            out.append(rec)
        return out


class SqliteAuditStore:
    def __init__(self, backend: SqliteBackend):
        self._db = backend
        self._lock = threading.Lock()

    def record(self, action: str, subject: str | None = None,
               outcome: str = "ok", detail: str | None = None) -> dict:
        from .audit import current_actor  # local import: audit imports us

        rec: dict[str, Any] = {
            "time": int(time.time()),
            "action": action,
            "subject": subject,
            "outcome": outcome,
            "actor": current_actor(),
        }
        if detail:
            rec["detail"] = str(detail)[:200]
        with self._lock:
            self._db.execute(
                "INSERT INTO audit_events"
                " (time, action, subject, outcome, detail, actor)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (rec["time"], action, subject, outcome, rec.get("detail"),
                 rec["actor"]),
            )
        return rec

    def recent(self, limit: int = 50) -> list:
        rows = self._db.query(
            "SELECT time, action, subject, outcome, detail, actor"
            " FROM audit_events ORDER BY seq DESC LIMIT ?", (limit,))
        out = []
        for r in reversed(rows):
            item = {
                "time": r["time"],
                "action": r["action"],
                "subject": r["subject"],
                "outcome": r["outcome"],
            }
            if r["detail"]:
                item["detail"] = r["detail"]
            if r["actor"]:
                item["actor"] = r["actor"]
            out.append(item)
        return out


# --------------------------------------------------------------------------
# Bundles + migration
# --------------------------------------------------------------------------


class Repository:
    """A bundle of the six stores backed by one storage engine."""

    def __init__(self, backend: str, *, api_keys, receipts, log,
                 notifications, revocation_index, audit):
        self.backend = backend
        self.api_keys = api_keys
        self.receipts = receipts
        self.log = log
        self.notifications = notifications
        self.revocation_index = revocation_index
        self.audit = audit

    def close(self) -> int:
        """Release storage handles; returns how many distinct engines closed.

        Every connection in this implementation is per-call and already closed
        by the time a query returns, so today this mostly drops the bundle. It
        exists because "graceful shutdown releases the repository" has to be a
        callable contract before a pooled backend (Redis/Postgres) can ever be
        dropped in — and a no-op that is never called would silently become a
        leak in exactly that future.
        """
        engines = []
        for name in ("api_keys", "receipts", "log", "notifications",
                     "revocation_index", "audit"):
            engine = getattr(getattr(self, name), "_db", None)
            if engine is not None and engine not in engines:
                engines.append(engine)
        closed = 0
        for engine in engines:
            close = getattr(engine, "close", None)
            if callable(close):
                close()
                closed += 1
        return closed


def close_all() -> int:
    """Close every cached bundle, clear the cache, return the bundle count."""
    with _BUNDLES_LOCK:
        bundles = list(_BUNDLES.values())
        _BUNDLES.clear()
    for bundle in bundles:
        bundle.close()
    return len(bundles)


def json_repository() -> Repository:
    return Repository(
        "json",
        api_keys=JsonApiKeyStore(),
        receipts=JsonReceiptStore(),
        log=JsonLogStore(),
        notifications=JsonNotificationStore(),
        revocation_index=JsonRevocationIndexStore(),
        audit=JsonAuditStore(),
    )


def sqlite_repository(path: str | os.PathLike | None = None) -> Repository:
    backend = SqliteBackend(path)
    backend.ensure_schema()
    return Repository(
        "sqlite",
        api_keys=SqliteApiKeyStore(backend),
        receipts=SqliteReceiptStore(backend),
        log=SqliteLogStore(backend),
        notifications=SqliteNotificationStore(backend),
        revocation_index=SqliteRevocationIndexStore(backend),
        audit=SqliteAuditStore(backend),
    )


def open_repository(backend: str | None = None) -> Repository:
    """Pick the configured backend (``STORAGE_BACKEND``), default JSON."""
    choice = (backend or cfg.STORAGE_BACKEND or "json").lower()
    if choice == "sqlite":
        return sqlite_repository()
    return json_repository()


def _read_jsonl_tail(path: Path, limit: int = 2000) -> list:
    out = []
    try:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def migrate_json_to_sqlite(path: str | os.PathLike | None = None) -> dict:
    """One-shot import of the JSON files into SQLite.

    Guarded by a ``meta`` row (``migration_version``): the second call imports
    nothing and reports ``already_migrated``. Returns per-store counts.
    """
    backend = SqliteBackend(path)
    backend.ensure_schema()
    existing = backend.query(
        "SELECT value FROM meta WHERE key = 'migration_version'")
    if existing and existing[0]["value"] == MIGRATION_VERSION:
        return {"already_migrated": True, "api_keys": 0, "receipts": 0,
                "log": 0, "notifications": 0}

    keys = _json_read(cfg.BASE_DIR / "data" / "apikeys.json", {})
    receipts = _read_receipts(cfg.BASE_DIR / "data" / "receipts.json")
    log_recs = _read_jsonl_tail(cfg.CHAIN_DIR.parent / "public-log.jsonl")
    notifications = _read_jsonl_tail(cfg.CHAIN_DIR.parent / "notifications.jsonl")

    counts = {"already_migrated": False, "api_keys": 0, "receipts": 0,
              "log": 0, "notifications": 0}

    if isinstance(keys, dict):
        for kid, rec in keys.items():
            backend.execute(
                "INSERT OR IGNORE INTO api_keys (id, name, created_at,"
                " last_used_at, revoked, hash) VALUES (?, ?, ?, ?, ?, ?)",
                (kid, rec.get("name"), rec.get("created_at"),
                 rec.get("last_used_at"), 1 if rec.get("revoked") else 0,
                 rec.get("hash") or ""),
            )
            counts["api_keys"] += 1

    if isinstance(receipts, list):
        for rec in receipts:
            if not isinstance(rec, dict) or not rec.get("receipt_id"):
                continue
            backend.execute(
                "INSERT OR IGNORE INTO receipts (receipt_id, hashed_document,"
                " verdict, verified_at, endpoint) VALUES (?, ?, ?, ?, ?)",
                (rec.get("receipt_id"), rec.get("hashed_document"),
                 rec.get("verdict"), rec.get("verified_at"),
                 rec.get("endpoint")),
            )
            counts["receipts"] += 1

    for rec in log_recs:
        if "time" not in rec:
            continue
        backend.execute(
            "INSERT INTO log_entries (time, hash_prefix, verdict) VALUES (?, ?, ?)",
            (int(rec.get("time") or 0), rec.get("hash_prefix"),
             rec.get("verdict")),
        )
        counts["log"] += 1

    for rec in notifications:
        if "time" not in rec:
            continue
        backend.execute(
            "INSERT INTO notifications (time, to_addr, subject, status, detail,"
            " url) VALUES (?, ?, ?, ?, ?, ?)",
            (int(rec.get("time") or 0), rec.get("to"), rec.get("subject"),
             rec.get("status"), rec.get("detail"), rec.get("url")),
        )
        counts["notifications"] += 1

    backend.execute(
        "INSERT INTO meta (key, value) VALUES ('migration_version', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (MIGRATION_VERSION,),
    )
    return counts


# --------------------------------------------------------------------------
# Late-bound accessor used by the storage modules (U2.2)
# --------------------------------------------------------------------------

_BUNDLES: dict[tuple, Repository] = {}
_BUNDLES_LOCK = threading.Lock()


def _cache_key(backend: str) -> tuple:
    """Identity of a backend *including* every path it captured.

    ``CHAIN_DIR`` is set by the tests through the environment before import,
    but a few suites rebind it later. Keying the cache on the live roots means
    a rebound directory transparently gets its own bundle instead of silently
    reading the previous location (the "green tests, stale log file" trap).
    """
    if backend == "sqlite":
        return ("sqlite", str(cfg.SQLITE_PATH))
    return ("json", str(cfg.BASE_DIR), str(cfg.CHAIN_DIR))


def _bundle_for(backend: str) -> Repository:
    key = _cache_key(backend)
    with _BUNDLES_LOCK:
        bundle = _BUNDLES.get(key)
        if bundle is None:
            bundle = (sqlite_repository() if backend == "sqlite"
                      else json_repository())
            _BUNDLES[key] = bundle
        return bundle


def store(name: str):
    """Return one store of the configured backend (lazily built, cached)."""
    backend = (cfg.STORAGE_BACKEND or "json").lower()
    return getattr(_bundle_for(backend), name)


def reset_store_cache() -> None:
    """Drop cached bundles (tests / backend switches)."""
    with _BUNDLES_LOCK:
        _BUNDLES.clear()
