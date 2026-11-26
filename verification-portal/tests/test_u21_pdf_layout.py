"""U21 — the card's layout is data now, and long fields cannot push it off the page.

Two failures this addresses, both invisible until someone looks at a rendered
PDF:

* every position was a literal (``22.6 * mm``) inside the renderer, so "do the
  QR and the revocation band collide?" could only be answered by eye, and any
  edit to a neighbour changed the answer silently;
* an over-long field (a thesis title, a verbose observation) grew the row block
  and pushed the hash box, the QR and finally the red bands off the page — a
  verdict with no way left to check it.

``LAYOUT`` + ``layout_zones`` + ``layout_conflicts`` make the first a test, and
a body floor with an explicit truncation note handles the second.
"""

import copy
import io
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u21-",
    ADMIN_TOKEN="u21-admin-token",
    CAPABILITY_SECRET="u21-capability-secret",
    PUBLIC_MODE="0",
)

from app import chain_service, pdf_diploma  # noqa: E402
from app.pdf_diploma import (LAYOUT, layout_conflicts, layout_zones,  # noqa: E402
                             render_diploma_pdf)


def _hash():
    chain_service.ensure_chain()
    doc = copy.deepcopy(chain_service.SAMPLE_DIPLOMA)
    raw = chain_service.CHAIN_DIR / "rawjsondocs" / f"{chain_service.hash_of(doc)}.json"
    if not raw.exists():
        chain_service.issue(doc)
    return doc, chain_service.hash_of(doc)


def _read(content):
    from pypdf import PdfReader
    return PdfReader(io.BytesIO(content))


def _text(reader):
    return "\n".join((p.extract_text() or "") for p in reader.pages)


class LayoutZoneTest(unittest.TestCase):
    # ---- the geometry is testable ------------------------------------
    def test_the_default_card_has_no_collisions(self):
        self.assertEqual(layout_conflicts(layout_zones(162)), [])

    def test_a_revoked_broken_chain_still_has_no_collisions(self):
        zones = layout_zones(162, has_revocation=True, has_integrity=True)
        self.assertEqual(layout_conflicts(zones), [])

    def test_the_conflict_check_can_actually_fail(self):
        """A self-check that always returns [] would pass this module and mean nothing."""
        bad = {"a": (0, 10), "b": (9, 20)}
        self.assertTrue(layout_conflicts(bad))

    def test_the_second_hash_row_is_inside_the_box(self):
        self.assertLess(LAYOUT["hash_line2_offset"], LAYOUT["hash_box_h"],
                        "the last hash characters must not print below the grey field")

    def test_the_qr_clears_the_hash_box_and_the_red_bands(self):
        zones = layout_zones(162, has_revocation=True, has_integrity=True)
        qr_bottom, qr_top = zones["qr"]
        self.assertGreater(qr_top, zones["hash_box"][0] - 1.5,
                           "QR must start below the hash box")
        self.assertGreater(qr_bottom, zones["revocation"][1] + 4,
                           "QR must stay clear of the revocation band")


class LongFieldTest(unittest.TestCase):
    def setUp(self):
        self.doc, self.hash = _hash()
        # Every row long enough to need four wrapped lines: the card holds eight
        # rows, so this is ~198mm of text where ~90mm is available.
        filler = ("Electronic and Electrical Engineering with a specialisation "
                  "in signal processing and embedded systems ") * 6
        self.long = copy.deepcopy(self.doc)
        pp = self.long["PersonalParticulars"]
        pp["GivenNames"] = filler
        pp["Surname"] = filler
        pp["StudentID"] = filler
        pp["DOB"] = "1988 " * 40
        ai = self.long["AcademicInfo"]
        ai["DegreeName"] = filler
        ai["Observations"] = filler
        ai["Honour"] = filler
        di = self.long["DocumentInfo"]
        di["AuthorizedSignature"] = "Prof. " + filler
        di["DateOfIssue"] = "2026 " * 40

    def test_a_long_field_does_not_overflow_the_card(self):
        pdf = render_diploma_pdf(self.long, self.hash, "http://127.0.0.1:8013")
        reader = _read(pdf)
        self.assertEqual(len(reader.pages), 1)
        text = _text(reader)
        self.assertIn("fields too long for the card", text)
        self.assertIn("This PDF carries the exact credential JSON", text)

    def test_the_qr_survives_a_long_field(self):
        pdf = render_diploma_pdf(self.long, self.hash, "http://127.0.0.1:8013")
        page = _read(pdf).pages[0]
        self.assertEqual(len(list(page.images)), 1,
                         "an over-long field must not cost the page its QR")

    def test_a_normal_card_is_not_truncated(self):
        pdf = render_diploma_pdf(self.doc, self.hash, "http://127.0.0.1:8013")
        self.assertNotIn("fields too long for the card", _text(_read(pdf)))

    def test_both_hash_rows_are_printable(self):
        pdf = render_diploma_pdf(self.doc, self.hash, "http://127.0.0.1:8013")
        flat = "".join(_text(_read(pdf)).split())
        self.assertIn(self.hash[:40], flat)
        if len(self.hash) > 84:
            self.assertIn(self.hash[84:110], flat, "second hash row went missing")

    def test_a_long_field_with_both_bands_still_fits(self):
        pdf = render_diploma_pdf(self.long, self.hash, "http://127.0.0.1:8013",
                                 revocation={"height": 4, "reason": "U21 sample"},
                                 integrity={"ok": False, "bad_blocks": [3]})
        reader = _read(pdf)
        text = _text(reader)
        self.assertEqual(len(reader.pages), 1)
        self.assertIn("REVOKED ON CHAIN", text)
        self.assertIn("CHAIN INTEGRITY FAILED", text)
        self.assertIn("fields too long for the card", text)


if __name__ == "__main__":
    unittest.main()
