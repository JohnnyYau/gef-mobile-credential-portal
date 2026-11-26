"""Batch U9-A — the receipt registry must stay O(1) per verification.

The original implementation parsed the whole receipts file and re-encoded it on
every verification: 63.7 ms of a 74 ms request at a few hundred receipts, and
a full rewrite on every request once the file reached RECEIPT_REGISTRY_CAP.
It now appends one line, with the legacy JSON-array layout migrated on the
writing path, so these tests pin down:

* both on-disk layouts are readable (old array + new lines),
* appending does not rewrite the file (line count +1, not a compaction),
* the cap is still enforced, with slack so it is not enforced per append,
* `get()` still finds receipts written by another instance / process.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repository import (  # noqa: E402
    JsonReceiptStore,
    _read_receipts,
    _write_receipts_lines,
)


def _record(i: int) -> dict:
    return {"receipt_id": f"RCP-{i:08x}-AA", "hashed_document": "H" * 86,
            "verdict": "VALID ON CHAIN", "verified_at": 1000.0 + i,
            "endpoint": "verify/hash"}


class _TempStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gef26-receipts-"))
        self.path = self.tmp / "receipts.json"

    def tearDown(self):
        for child in self.tmp.iterdir():
            child.unlink()
        self.tmp.rmdir()

    def _line_count(self) -> int:
        return len(self.path.read_text(encoding="utf-8").splitlines())


class ReceiptLayoutTests(_TempStoreTest):
    def test_legacy_json_array_is_still_read(self):
        records = [_record(i) for i in range(3)]
        self.path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        self.assertEqual(_read_receipts(self.path), records)

    def test_line_layout_round_trips(self):
        records = [_record(i) for i in range(3)]
        _write_receipts_lines(self.path, records)
        self.assertEqual(_read_receipts(self.path), records)
        self.assertEqual(self._line_count(), 3)

    def test_missing_and_torn_tail(self):
        self.assertEqual(_read_receipts(self.path), [])
        self.path.write_text('{"receipt_id": "A"}\n{"receipt_id": "B"}\n{"rec',
                             encoding="utf-8")
        self.assertEqual([r["receipt_id"] for r in _read_receipts(self.path)],
                         ["A", "B"], "a torn last line must not lose the file")

    def test_empty_file_reads_as_empty(self):
        self.path.write_text("", encoding="utf-8")
        self.assertEqual(_read_receipts(self.path), [])


class RegisterIsAppendOnlyTests(_TempStoreTest):
    def test_legacy_array_is_migrated_on_first_write(self):
        self.path.write_text(json.dumps([_record(0)], indent=2), encoding="utf-8")
        store = JsonReceiptStore(path=self.path, cap=100)
        rid = store.register("H" * 86, "VALID ON CHAIN", 1234.0, "verify/hash")
        self.assertEqual(self._line_count(), 2)
        self.assertEqual(_read_receipts(self.path)[-1]["receipt_id"], rid)

    def test_appends_do_not_rewrite_the_file(self):
        _write_receipts_lines(self.path, [_record(i) for i in range(200)])
        store = JsonReceiptStore(path=self.path, cap=200)
        store.register("H" * 86, "VALID", 1.0, "verify/hash")   # first call compacts
        lines_before = self._line_count()
        for _ in range(5):
            store.register("H" * 86, "VALID", 1.0, "verify/hash")
        self.assertEqual(self._line_count(), lines_before + 5,
                         "each append must add exactly one line, no full rewrite")

    def test_cap_is_enforced_with_slack_not_per_append(self):
        store = JsonReceiptStore(path=self.path, cap=3)
        for i in range(12):
            store.register("H" * 86, "VALID", 1.0 + i, "verify/hash")
        # cap 3 + slack max(8, 0) = 11 lines before compaction collapses to 3
        self.assertLessEqual(self._line_count(), 12)
        kept = _read_receipts(self.path)
        self.assertLessEqual(len(kept), 3)
        self.assertEqual(kept[-1]["verified_at"], 1.0 + 11,
                         "compaction must keep the newest receipts")

    def test_get_finds_a_receipt_written_by_another_instance(self):
        writer = JsonReceiptStore(path=self.path, cap=100)
        rid = writer.register("H" * 86, "VALID", 2.0, "verify/hash")
        reader = JsonReceiptStore(path=self.path, cap=100)
        self.assertEqual(reader.get(rid)["receipt_id"], rid)

    def test_get_returns_none_for_an_unknown_id(self):
        store = JsonReceiptStore(path=self.path, cap=100)
        store.register("H" * 86, "VALID", 3.0, "verify/hash")
        self.assertIsNone(store.get("RCP-does-not-exist"))


if __name__ == "__main__":
    unittest.main()
