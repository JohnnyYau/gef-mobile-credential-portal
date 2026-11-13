"""pdf_diploma.py — verifiable diploma PDFs (post-Week-3 extra A).

The exact credential JSON is embedded in the PDF as a file attachment, so
verification stays exact (no OCR): the portal renders a human-readable diploma
card, then appends ``credential.json`` as an embedded file. A verifier uploads
the PDF, we read the attachment and run the normal six-check verification.

The chain never stores the plaintext — the PDF only carries the student's own
copy of the JSON, and the verdict still comes from the chain's hashes.

Requires: reportlab (render) and pypdf (embed/extract) — both in
requirements.txt.
"""

import io
import json
import warnings

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

try:
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase import pdfmetrics as _pdfmetrics
    _pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _CJK_FONT = "STSong-Light"
except Exception:  # CID fonts unavailable -> ASCII-only rendering
    _CJK_FONT = None

try:
    import qrcode
except ImportError:  # QR on the PDF is decorative; the hash still prints
    qrcode = None

ATTACHMENT_NAME = "credential.json"


def _font_for(text, bold=False):
    """STSong-Light when the text contains CJK, Helvetica otherwise."""
    if _CJK_FONT and any(ord(ch) > 127 for ch in str(text)):
        return _CJK_FONT
    return "Helvetica-Bold" if bold else "Helvetica"


def _quiet_pypdf():
    """pypdf warns 'EOF marker not found' on some well-formed appended files;
    pdfinfo and roundtrip parsing both succeed, so silence that noise."""
    warnings.filterwarnings("ignore", message=".*EOF marker not found.*")


def _wrap_text(text, size, width, font="Helvetica"):
    """Greedy word-wrap for reportlab (no textobject wrapping built in)."""
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if stringWidth(trial, font, size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_diploma_pdf(document: dict, hashed_document: str, base_url: str) -> bytes:
    """Render a printable diploma card and embed the credential JSON.

    Returns the raw PDF bytes. The student/verifier can print the card; the
    portal verifies it from the embedded JSON — pixel-perfect fields are not
    needed, because nothing is OCR'd.
    """
    pp = document.get("PersonalParticulars", {})
    ai = document.get("AcademicInfo", {})
    di = document.get("DocumentInfo", {})

    buf = io.BytesIO()
    W, H = A4
    c = canvas.Canvas(buf, pagesize=A4)
    margin = 20 * mm

    # header band
    c.setFillColorRGB(0.06, 0.35, 0.33)
    c.rect(0, H - 32 * mm, W, 32 * mm, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(_font_for(di.get("IssuingO", "UNIVERSITY")[:44], bold=True), 20)
    c.drawString(margin, H - 20 * mm, di.get("IssuingO", "UNIVERSITY")[:44])
    c.setFont(_font_for(di.get("IssuingOU", "RECORD OFFICE")[:60]), 11)
    c.drawString(margin, H - 27 * mm, di.get("IssuingOU", "RECORD OFFICE")[:60])

    # title
    c.setFillColorRGB(0.09, 0.13, 0.18)
    c.setFont(_font_for(di.get("DocType", "CERTIFICATE").upper(), bold=True), 15)
    c.drawString(margin, H - 45 * mm, di.get("DocType", "CERTIFICATE").upper())

    y = H - 55 * mm
    c.setFont("Helvetica", 11.5)
    rows = [
        ("Student name", f"{pp.get('GivenNames', '')} {pp.get('Surname', '')}".strip()),
        ("Student ID", pp.get("StudentID", "—")),
        ("Date of birth", pp.get("DOB", "—")),
        ("Degree / content", ai.get("DegreeName", "—")),
        ("Period", f"{ai.get('DegreeStartDate', '—')} → {ai.get('DegreeEndDate', '—')}"),
        ("Honour / note", ai.get("Honour") or ai.get("Observations") or "—"),
        ("Date of issue", di.get("DateOfIssue", "—")),
        ("Signed", di.get("AuthorizedSignature", "—")),
    ]
    for label, value in rows:
        c.setFillColorRGB(0.30, 0.38, 0.46)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(margin, y, label)
        c.setFillColorRGB(0.09, 0.13, 0.18)
        fname = _font_for(value)
        c.setFont(fname, 10.5)
        lines = _wrap_text(value, 10.5, 120 * mm, font=fname)
        for i, line in enumerate(lines[:4]):
            c.drawString(margin + 40 * mm, y - i * 5.2 * mm, line)
        y -= (max(1, len(lines[:4])) * 5.2 * mm) + 4 * mm

    # hash box
    y -= 6 * mm
    c.setFillColorRGB(0.96, 0.98, 0.99)
    c.roundRect(margin, y - 16 * mm, 170 * mm, 16 * mm, 2 * mm, stroke=0, fill=1)
    c.setFillColorRGB(0.09, 0.13, 0.18)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin + 4 * mm, y - 9 * mm, "ON-CHAIN HASH (sha3_512)")
    c.setFont("Courier", 8.5)
    c.drawString(margin + 4 * mm, y - 14 * mm, hashed_document[:84])
    c.drawString(margin + 4 * mm, y - 17.4 * mm, hashed_document[84:168] if len(hashed_document) > 84 else "")

    # QR
    if qrcode is not None:
        try:
            qr = qrcode.make(f"{base_url}/verify?hash={hashed_document}")
            qr_io = io.BytesIO()
            qr.save(qr_io, format="PNG")
            c.drawImage(qr_io, W - margin - 28 * mm, y - 44 * mm,
                        width=28 * mm, height=28 * mm, preserveAspectRatio=True)
            c.setFillColorRGB(0.30, 0.38, 0.46)
            c.setFont("Helvetica", 7.5)
            c.drawString(W - margin - 28 * mm, y - 47 * mm, "Scan to verify")
        except Exception:
            pass  # decorative only

    # footer
    c.setFillColorRGB(0.42, 0.47, 0.53)
    c.setFont("Helvetica", 8)
    c.drawString(margin, 18 * mm,
                 "This PDF carries the exact credential JSON as an embedded file.")
    c.drawString(margin, 14.5 * mm,
                 "Upload it to the verification portal for the cryptographic verdict — no OCR involved.")
    c.showPage()
    c.save()

    # attach the exact JSON
    out = io.BytesIO()
    with warnings.catch_warnings():
        _quiet_pypdf()
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.append(buf)
        # pypdf's add_attachment encodes latin-1; escape non-ASCII so Chinese
        # names (e.g. 燒雞) survive. json.loads restores the same dict.
        writer.add_attachment(ATTACHMENT_NAME,
                              json.dumps(document, ensure_ascii=True))
        writer.write(out)
    return out.getvalue()


def extract_credential(raw: bytes) -> dict:
    """Pull the embedded credential JSON out of a portal-issued PDF."""
    with warnings.catch_warnings():
        _quiet_pypdf()
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(raw))
        except Exception as exc:
            raise ValueError(
                f"Could not read PDF ({exc}). Only portal-issued PDFs carrying an "
                f"embedded {ATTACHMENT_NAME} can be verified — upload the .json "
                "file or paste the JSON below instead."
            ) from exc
    attachments = reader.attachments or {}
    if ATTACHMENT_NAME not in attachments:
        raise ValueError(
            "This PDF has no embedded credential.json. Only portal-issued "
            "diploma PDFs can be verified this way — upload the .json file "
            "or paste the JSON below instead."
        )
    attached = attachments[ATTACHMENT_NAME]
    attached = attached[0] if isinstance(attached, list) else attached
    data = attached.get_data() if hasattr(attached, "get_data") else attached
    try:
        return json.loads(data)
    except (ValueError, TypeError) as exc:
        raise ValueError("Embedded credential.json in the PDF is corrupt.") from exc
