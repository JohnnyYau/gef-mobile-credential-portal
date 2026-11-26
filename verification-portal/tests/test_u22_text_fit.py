"""U22 — single-line strings are fitted by measured width, not by character count.

The header cut the institution name with ``[:44]``. Forty-four characters says
nothing about millimetres: at 20pt, 44 Latin glyphs are about 150mm (tight but
possible), and 44 CJK glyphs are about 310mm — 100mm off the right edge of an
A4 page. The same class of bug lived in ``_wrap_text``, which appended any token
wider than the column as a whole line, so an unbroken 300-character ID or URL
ran off the card.

Everything drawn as one line now passes through ``_fit_text`` (binary-search to
the longest prefix that fits, plus ``...``), and ``_wrap_text`` hard-breaks a
token that cannot fit by itself.
"""

import io
import unittest

from tests._bootstrap import isolated_chain_dir

_TMP = isolated_chain_dir(
    prefix="portal-u22-",
    ADMIN_TOKEN="u22-admin-token",
    CAPABILITY_SECRET="u22-capability-secret",
    PUBLIC_MODE="0",
)

import copy  # noqa: E402

from app import chain_service  # noqa: E402
from app.pdf_diploma import (LAYOUT, _fit_text, _wrap_text,  # noqa: E402
                             render_diploma_pdf, stringWidth, mm)

PAGE_W = 210 * mm
MARGIN = 20 * mm
COL_W = PAGE_W - 2 * MARGIN


def _read(content):
    from pypdf import PdfReader
    return PdfReader(io.BytesIO(content))


def _text(reader):
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _doc_and_hash():
    chain_service.ensure_chain()
    doc = copy.deepcopy(chain_service.SAMPLE_DIPLOMA)
    raw = chain_service.CHAIN_DIR / "rawjsondocs" / f"{chain_service.hash_of(doc)}.json"
    if not raw.exists():
        chain_service.issue(doc)
    return doc, chain_service.hash_of(doc)


class FitTextTest(unittest.TestCase):
    def test_short_text_is_returned_unchanged(self):
        self.assertEqual(_fit_text("UNIVERSITY OF UTOPIA", 20, COL_W), "UNIVERSITY OF UTOPIA")

    def test_long_text_fits_and_is_marked(self):
        long = "UNIVERSITY " * 40
        fitted = _fit_text(long, 20, COL_W)
        self.assertLessEqual(stringWidth(fitted, "Helvetica", 20), COL_W)
        self.assertTrue(fitted.endswith("..."))
        self.assertTrue(long.startswith(fitted[:-3]))

    def test_a_cjk_name_is_measured_not_counted(self):
        """44 characters of Chinese at 20pt would be ~310mm — twice the page."""
        cjk = "香港理工大學電子及資訊工程學系" * 3
        fitted = _fit_text(cjk, 20, COL_W)
        self.assertLessEqual(stringWidth(fitted, "Helvetica", 20), COL_W)
        self.assertLess(len(fitted), len(cjk))

    def test_empty_string_stays_empty(self):
        self.assertEqual(_fit_text("", 20, COL_W), "")

    def test_exact_fit_is_not_truncated(self):
        width = stringWidth("ABCDEFGHIJ", "Helvetica", 10)
        self.assertEqual(_fit_text("ABCDEFGHIJ", 10, width), "ABCDEFGHIJ")


class WrapTextTest(unittest.TestCase):
    def test_an_unbreakable_token_is_split(self):
        lines = _wrap_text("A" * 300, 10.5, 120 * mm)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(stringWidth(line, "Helvetica", 10.5), 120 * mm)

    def test_normal_words_are_not_split(self):
        text = "Bachelor of Engineering in Electronic and Electrical Engineering"
        lines = _wrap_text(text, 10.5, 120 * mm)
        self.assertEqual(" ".join(lines), text)

    def test_the_wrapped_block_stays_inside_the_column(self):
        for width in (60, 120, 170):
            for line in _wrap_text(("word " * 400).strip(), 10.5, width * mm):
                self.assertLessEqual(stringWidth(line, "Helvetica", 10.5), width * mm)


class RenderedWidthTest(unittest.TestCase):
    def setUp(self):
        self.doc, self.hash = _doc_and_hash()

    def test_a_long_institution_name_is_trimmed_on_the_page(self):
        doc = copy.deepcopy(self.doc)
        doc["DocumentInfo"]["IssuingO"] = "UNIVERSITY OF " + ("LONG NAME " * 30)
        pdf = render_diploma_pdf(doc, self.hash, "http://127.0.0.1:8013")
        reader = _read(pdf)
        self.assertEqual(len(reader.pages), 1)
        self.assertIn("...", _text(reader))

    def test_an_unbroken_student_id_wraps_instead_of_overflowing(self):
        doc = copy.deepcopy(self.doc)
        doc["PersonalParticulars"]["StudentID"] = "22000000" * 30
        pdf = render_diploma_pdf(doc, self.hash, "http://127.0.0.1:8013")
        page = _read(pdf).pages[0]
        self.assertEqual(len(list(page.images)), 1, "QR must survive a long ID")

    def test_every_fixed_sentence_fits_its_own_size(self):
        """The footer and the integrity note are constants; this catches a copy edit."""
        sentences = [
            ("This is a verification report for an on-chain hash. Identity fields are withheld.", 8),
            ("The credential PDF is issued to its holder through a personal link, "
             "not to anyone holding the hash.", 8),
            ("This PDF carries the exact credential JSON as an embedded file.", 8),
            ("Upload it to the verification portal for the cryptographic verdict — no OCR involved.", 8),
            ("Other blocks on this chain failed to verify; this report's verdict "
             "may be unreliable. See /healthz.", 7.4),
            ("VERIFICATION REPORT — identity withheld; not the credential itself", 8.5),
        ]
        for text, size in sentences:
            self.assertLessEqual(stringWidth(text, "Helvetica", size), COL_W, text)

    def test_a_long_institution_name_is_fitted_at_its_own_size(self):
        """Extracted text loses font sizes, so measure the fitted string directly."""
        org = "UNIVERSITY OF " + ("LONG NAME " * 30)
        fitted = _fit_text(org, 20, COL_W, "Helvetica-Bold")
        self.assertLessEqual(stringWidth(fitted, "Helvetica-Bold", 20), COL_W)
        self.assertTrue(fitted.endswith("..."))

    def test_the_layout_floor_is_unchanged_by_fitting(self):
        pdf = render_diploma_pdf(self.doc, self.hash, "http://127.0.0.1:8013")
        self.assertNotIn("fields too long for the card", _text(_read(pdf)))
        self.assertEqual(LAYOUT["hash_line2_offset"], 17.2)


if __name__ == "__main__":
    unittest.main()
