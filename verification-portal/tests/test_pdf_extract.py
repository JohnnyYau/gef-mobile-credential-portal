"""Round 9 — PDF auto-fill (POST /api/extract/pdf) tests.

Covers: byte-exact embedded-payload extraction from portal-issued PDFs,
label-aware text-layer extraction with confidence, friendly 422s for
scan-like / non-PDF uploads, and the shared upload-size guard.
Isolated chain like test_issue_batch (fresh CHAIN_DIR + reloads).
"""

import importlib
import io
import os
import tempfile
import unittest

from fastapi.testclient import TestClient


def setUpModule():
    os.environ["CHAIN_DIR"] = os.path.join(
        tempfile.mkdtemp(prefix="gef26-extract-"), "chain")
    os.environ.pop("PUBLIC_MODE", None)
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.chain_service as cs_mod
    importlib.reload(cs_mod)
    from app import main as _m
    importlib.reload(_m)
    global app, client, MAX_UPLOAD_BYTES
    from app import config as _cfg
    app = _m.app
    client = TestClient(app)
    MAX_UPLOAD_BYTES = _cfg.MAX_UPLOAD_BYTES


def tearDownModule():
    os.environ.pop("PUBLIC_MODE", None)
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.chain_service as cs_mod
    importlib.reload(cs_mod)
    from app import main as _m
    importlib.reload(_m)


def _doc(surname="EXTRACT", given="AUTOFILL", student_id="99000021",
         dob="19990303", degree="Bachelor of Extraction"):
    return {
        "PersonalParticulars": {"Surname": surname, "GivenNames": given,
                                "Sex": "M", "DOB": dob, "StudentID": student_id},
        "AcademicInfo": {"DegreeName": degree, "DegreeStartDate": "20220901",
                         "DegreeEndDate": "20260801", "Honour": "FIRST HON",
                         "Observations": "AUTO FILL TEST"},
        "DocumentInfo": {"DateOfIssue": "20261001",
                         "AuthorizedSignature": "REGISTRAR EXTRACT",
                         "IssuingO": "UNIVERSITY OF UTOPIA",
                         "IssuingOU": "RECORD OFFICE",
                         "DocType": "CERTIFICATE OF DIPLOMA"},
    }


def _portal_pdf(document: dict) -> bytes:
    """A portal-issued diploma PDF with the exact JSON embedded."""
    from app import pdf_diploma
    return pdf_diploma.render_diploma_pdf(document, "H" * 168, "http://test")


def _text_pdf(lines) -> bytes:
    """A plain text-layer PDF with NO embedded attachment (foreign cert)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in lines:
        c.setFont("Helvetica", 11)
        c.drawString(72, y, line)
        y -= 24
    c.showPage()
    c.save()
    return buf.getvalue()


class PdfExtractTest(unittest.TestCase):

    def test_embedded_payload_exact(self):
        doc = _doc()
        r = client.post("/api/extract/pdf",
                        files={"file": ("diploma.pdf", _portal_pdf(doc),
                                        "application/pdf")})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["mode"], "embedded_payload")
        self.assertEqual(data["confidence"], 1.0)
        self.assertEqual(data["document"], doc)  # byte-exact round-trip
        self.assertTrue(data["note"])

    def test_text_layer_extraction(self):
        pdf = _text_pdf([
            "UNIVERSITY OF UTOPIA",
            "CERTIFICATE OF DIPLOMA",
            "Surname: EXTRACT",
            "Given Names: AUTOFILL",
            "Student ID: 99000021",
            "Date of Birth: 19990303",
            "Degree Name: Bachelor of Extraction",
            "Honour: FIRST HON",
            "Issuing Organisation: UNIVERSITY OF UTOPIA",
            "Date of Issue: 20261001",
            "Authorized Signature: REGISTRAR EXTRACT",
        ])
        r = client.post("/api/extract/pdf",
                        files={"file": ("foreign.pdf", pdf, "application/pdf")})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["mode"], "text_extract")
        self.assertGreater(data["confidence"], 0.7)
        d = data["document"]
        pp = d["PersonalParticulars"]
        ai = d["AcademicInfo"]
        di = d["DocumentInfo"]
        self.assertEqual(pp["Surname"], "EXTRACT")
        self.assertEqual(pp["GivenNames"], "AUTOFILL")
        self.assertEqual(pp["StudentID"], "99000021")
        self.assertEqual(pp["DOB"], "19990303")
        self.assertEqual(ai["DegreeName"], "Bachelor of Extraction")
        self.assertEqual(ai["Honour"], "FIRST HON")
        self.assertEqual(di["IssuingO"], "UNIVERSITY OF UTOPIA")
        self.assertEqual(di["DateOfIssue"], "20261001")
        self.assertEqual(di["DocType"], "CERTIFICATE OF DIPLOMA")
        self.assertTrue(data["field_confidence"])
        self.assertIsInstance(data["warnings"], list)

    def test_scan_like_pdf_422(self):
        # blank page -> no text layer -> friendly 422, not a fake result
        pdf = _text_pdf([])
        r = client.post("/api/extract/pdf",
                        files={"file": ("scan.pdf", pdf, "application/pdf")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("文本层", r.json()["detail"])

    def test_non_pdf_422(self):
        r = client.post("/api/extract/pdf",
                        files={"file": ("cred.json", b'{"a": 1}', "application/json")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("PDF", r.json()["detail"])

    def test_oversized_413(self):
        big = b"%PDF-1.4\n" + b"x" * MAX_UPLOAD_BYTES
        r = client.post("/api/extract/pdf",
                        files={"file": ("big.pdf", big, "application/pdf")})
        self.assertEqual(r.status_code, 413)

    def test_corrupted_pdf_422(self):
        r = client.post("/api/extract/pdf",
                        files={"file": ("broken.pdf", b"%PDF-1.4\nbroken", "application/pdf")})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
