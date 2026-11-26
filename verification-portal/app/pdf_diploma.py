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
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

try:
    from reportlab.pdfbase import pdfmetrics as _pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    _pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _CJK_FONT = "STSong-Light"
except Exception:  # CID fonts unavailable -> ASCII-only rendering
    _CJK_FONT = None

try:
    import qrcode
except ImportError:  # QR on the PDF is decorative; the hash still prints
    qrcode = None

from pypdf.errors import PyPdfError as _PdfReadError

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
    """Greedy word-wrap for reportlab (no textobject wrapping built in).

    U22: a token wider than the column (a URL, an unbroken 300-character ID)
    used to be appended whole and simply run off the page. It is now broken
    character by character, which is the only thing that keeps ``width`` a
    promise for arbitrary input.
    """
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        if stringWidth(w, font, size) > width:
            if cur:
                lines.append(cur)
                cur = ""
            chunk = ""
            for ch in w:
                if chunk and stringWidth(chunk + ch, font, size) > width:
                    lines.append(chunk)
                    chunk = ch
                else:
                    chunk += ch
            cur = chunk
            continue
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


def _fit_text(text, size, width, font="Helvetica", ellipsis="..."):
    """Trim a single-line string until it fits ``width`` points.

    U22: several header strings were cut by *character count* (``[:44]``),
    which says nothing about width — 44 CJK glyphs at 20pt are about 310mm on a
    210mm page. Anything drawn as one line now goes through this instead.
    """
    s = str(text)
    if stringWidth(s, font, size) <= width:
        return s
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if stringWidth(s[:mid] + ellipsis, font, size) <= width:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo] + ellipsis


# --- layout ---------------------------------------------------------------
#
# Every number that decides *where* something sits on the card lives here.
# Until U21 these were scattered through the renderer as ``22.6 * mm`` etc.,
# which made "does the QR collide with the revocation band" a question only a
# human looking at a PDF could answer — and the answer changed silently when
# someone edited a neighbouring constant. ``layout_zones`` turns the arithmetic
# into data so a test can assert the gaps.
#
# Distances are millimetres from the bottom of the A4 page, except the
# ``_offset`` values, which are measured downward from the running cursor ``y``
# (so a larger offset means lower on the page).
LAYOUT = {
    "hash_box_h": 18.0,
    "hash_title_offset": 9.0,
    "hash_line1_offset": 13.6,
    "hash_line2_offset": 17.2,
    "qr_size": 28.0,
    "qr_offset": 47.0,
    "qr_caption_offset": 50.0,
    "qr_small_size": 20.0,
    "qr_small_offset": 39.0,
    "qr_min_bottom": 43.0,
    "fallback_url_offset": 41.0,
    "fallback_step": 3.6,
    "revocation_bottom": 26.0,
    "revocation_h": 13.0,
    "integrity_main": 22.6,
    "integrity_note": 19.2,
    "footer_line1": 15.6,
    "footer_line2": 12.2,
    "body_floor": 100.0,
}

# Text baselines are treated as 2.4mm tall when checking for collisions.
_TEXT_H = 2.4


def layout_zones(y_mm, has_revocation=False, has_integrity=False,
                 qr_size_mm=None, qr_bottom_mm=None):
    """The vertical zones the card draws, in mm from the page bottom.

    ``y_mm`` is the cursor position where the hash box starts (top). Returns a
    name -> (bottom, top) mapping suitable for :func:`layout_conflicts`.
    """
    L = LAYOUT
    size = L["qr_size"] if qr_size_mm is None else qr_size_mm
    qr_bottom = (y_mm - L["qr_offset"]) if qr_bottom_mm is None else qr_bottom_mm
    zones = {
        "hash_box": (y_mm - L["hash_box_h"], y_mm),
        "qr": (qr_bottom, qr_bottom + size),
        "qr_caption": (y_mm - L["qr_caption_offset"] - _TEXT_H,
                       y_mm - L["qr_caption_offset"]),
        "footer_line1": (L["footer_line1"], L["footer_line1"] + _TEXT_H),
        "footer_line2": (L["footer_line2"], L["footer_line2"] + _TEXT_H),
    }
    if has_revocation:
        zones["revocation"] = (L["revocation_bottom"],
                               L["revocation_bottom"] + L["revocation_h"])
    if has_integrity:
        zones["integrity_main"] = (L["integrity_main"], L["integrity_main"] + _TEXT_H)
        zones["integrity_note"] = (L["integrity_note"], L["integrity_note"] + _TEXT_H)
    return zones


def layout_conflicts(zones, min_gap=0.8):
    """Pairs of zones whose vertical gap is below ``min_gap`` mm.

    Only vertical order is modelled: these zones are either full-width or on the
    right edge, and the pairs people actually get wrong are vertical.
    """
    items = list(zones.items())
    problems = []
    for i, (a, (ab, at)) in enumerate(items):
        for b, (bb, bt) in items[i + 1:]:
            gap = max(bb - at, ab - bt)
            if gap < min_gap:
                problems.append({"a": a, "b": b, "gap_mm": round(gap, 2)})
    return problems


def render_diploma_pdf(document: dict, hashed_document: str, base_url: str,
                       redact: bool = False,
                       revocation: dict | None = None,
                       integrity: dict | None = None) -> bytes:
    """Render a printable diploma card and embed the credential JSON.

    Returns the raw PDF bytes. The student/verifier can print the card; the
    portal verifies it from the embedded JSON — pixel-perfect fields are not
    needed, because nothing is OCR'd.

    ``redact=True`` renders the *verification report* variant used on the
    public entry point (U13 F1): the identity rows are withheld and the JSON
    attachment is omitted, so a bare hash never yields the plaintext
    credential. The credential itself is served only to its holder (through a
    capability link) or to staff.

    ``revocation`` (U14) is the latest REVOKE record for this hash, if any
    (``{"height": int|None, "reason": str|None}``). A PDF is a static
    artefact: without this band, a revoked credential keeps printing as a
    valid-looking diploma forever. The band cannot make the file valid again,
    but it stops it being mistaken for a live credential.

    ``integrity`` (U19) is the whole-chain check (``{"ok": bool,
    "bad_blocks": [int]}``). A credential's own block can be perfectly fine
    while a *later* block on the same chain failed to verify — and then every
    verdict, including this file's, reads INVALID. The file has to say so, or
    a recipient is left holding a clean-looking report with no hint that the
    source is broken.
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
    # U22: fit by width, not by a character count. The header is the one place
    # a long institution name (or a CJK name at 20pt) runs off the right edge.
    org = str(di.get("IssuingO", "UNIVERSITY"))
    org_font = _font_for(org, bold=True)
    c.setFont(org_font, 20)
    c.drawString(margin, H - 20 * mm,
                 _fit_text(org, 20, W - 2 * margin, org_font))
    unit = str(di.get("IssuingOU", "RECORD OFFICE"))
    unit_font = _font_for(unit)
    c.setFont(unit_font, 11)
    c.drawString(margin, H - 27 * mm,
                 _fit_text(unit, 11, W - 2 * margin, unit_font))

    # title
    c.setFillColorRGB(0.09, 0.13, 0.18)
    doc_type = str(di.get("DocType", "CERTIFICATE")).upper()
    doc_font = _font_for(doc_type, bold=True)
    c.setFont(doc_font, 15)
    c.drawString(margin, H - 45 * mm,
                 _fit_text(doc_type, 15, W - 2 * margin, doc_font))
    if redact:
        c.setFillColorRGB(0.55, 0.30, 0.10)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(margin, H - 50 * mm,
                     "VERIFICATION REPORT — identity withheld; not the credential itself")

    y = H - 55 * mm if not redact else H - 57 * mm
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
    if redact:
        rows[0] = ("Student name", "withheld")
        rows[1] = ("Student ID", "withheld")
        rows[2] = ("Date of birth", "withheld")
    L = LAYOUT
    truncated = False
    for label, value in rows:
        # U21: a very long field (a thesis title, a long observation) used to
        # push the hash box, the QR and eventually the revocation band off the
        # page. The decision has to include *this* row's height, otherwise the
        # last row can still end below the floor. The full values are always in
        # the embedded JSON; the note below says so.
        fname = _font_for(value)
        lines = _wrap_text(value, 10.5, 120 * mm, font=fname)[:4]
        height = (max(1, len(lines)) * 5.2 + 4) * mm
        if y - height < L["body_floor"] * mm:
            truncated = True
            break
        c.setFillColorRGB(0.30, 0.38, 0.46)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(margin, y, label)
        c.setFillColorRGB(0.09, 0.13, 0.18)
        c.setFont(fname, 10.5)
        for i, line in enumerate(lines):
            c.drawString(margin + 40 * mm, y - i * 5.2 * mm, line)
        y -= height
    if truncated:
        c.setFillColorRGB(0.52, 0.38, 0.14)
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(margin, y + 1 * mm,
                     "(fields too long for the card are complete in the embedded JSON)")

    # hash box
    y -= 6 * mm
    c.setFillColorRGB(0.96, 0.98, 0.99)
    c.roundRect(margin, y - L["hash_box_h"] * mm, 170 * mm,
                L["hash_box_h"] * mm, 2 * mm, stroke=0, fill=1)
    c.setFillColorRGB(0.09, 0.13, 0.18)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin + 4 * mm, y - L["hash_title_offset"] * mm,
                 "ON-CHAIN HASH (sha3_512)")
    c.setFont("Courier", 8.5)
    c.drawString(margin + 4 * mm, y - L["hash_line1_offset"] * mm, hashed_document[:84])
    # U21: the second row used to sit at y-17.4 inside a 16mm box, i.e. 1.4mm
    # *below* the box outline — the last two characters printed outside the grey
    # field. Box is 18mm now, so both rows are inside it.
    c.drawString(margin + 4 * mm, y - L["hash_line2_offset"] * mm,
                 hashed_document[84:168] if len(hashed_document) > 84 else "")

    # QR
    #
    # U19: this block used to fail silently on every render. ``canvas.drawImage``
    # does not accept a BytesIO — it wants a path, bytes, or an ImageReader — and
    # the TypeError was swallowed by the "decorative only" except below. So no
    # PDF ever carried a QR, while the code, the docs and six rounds of notes all
    # said it did. Wrapping the buffer in ImageReader fixes the type, and the
    # fallback below means a failed QR can no longer leave the page with no
    # entry point at all: the URL is printed instead.
    verify_url = f"{base_url}/verify?hash={hashed_document}"
    qr_drawn = False
    # U21: if the cursor sits low enough that a full-size QR would reach the
    # revocation band, shrink it once; if even that does not fit, skip the image
    # and let the URL fallback print. (The row bound above should make this
    # unreachable, so it is a second line of defence against future edits.)
    qr_size = L["qr_size"]
    qr_bottom = y - L["qr_offset"] * mm
    if qr_bottom < L["qr_min_bottom"] * mm:
        qr_size = L["qr_small_size"]
        qr_bottom = y - L["qr_small_offset"] * mm
    if qrcode is not None and qr_bottom >= L["qr_min_bottom"] * mm:
        try:
            qr = qrcode.make(verify_url)
            qr_io = io.BytesIO()
            qr.save(qr_io, format="PNG")
            qr_io.seek(0)
            c.drawImage(ImageReader(qr_io), W - margin - qr_size * mm, qr_bottom,
                        width=qr_size * mm, height=qr_size * mm,
                        preserveAspectRatio=True)
            c.setFillColorRGB(0.30, 0.38, 0.46)
            c.setFont("Helvetica", 7.5)
            c.drawString(W - margin - qr_size * mm,
                         qr_bottom - 3 * mm, "Scan to verify")
            qr_drawn = True
        except (OSError, ValueError, TypeError, KeyError):
            qr_drawn = False
    if not qr_drawn:
        # A URL has no spaces, so split by characters rather than _wrap_text’s
        # word wrapping (a single long token would overflow the page).
        c.setFillColorRGB(0.24, 0.31, 0.40)
        c.setFont("Helvetica", 7)
        url_line = "Verify online: " + verify_url
        for i in range(3):
            chunk = url_line[i * 108:(i + 1) * 108]
            if chunk:
                c.drawString(margin, y - L["fallback_url_offset"] * mm
                             - i * L["fallback_step"] * mm, chunk)

    # U14: a revoked credential must not print as a live one. A PDF cannot be
    # withdrawn once handed out, so the file carries the fact instead.
    if revocation:
        y0 = L["revocation_bottom"] * mm
        c.setFillColorRGB(0.99, 0.93, 0.93)
        c.setStrokeColorRGB(0.78, 0.20, 0.20)
        c.setLineWidth(1.2)
        c.roundRect(margin, y0, W - 2 * margin, L["revocation_h"] * mm,
                    2 * mm, stroke=1, fill=1)
        c.setFillColorRGB(0.70, 0.10, 0.10)
        c.setFont("Helvetica-Bold", 11)
        head = "REVOKED ON CHAIN"
        if revocation.get("height"):
            head += f" — block #{revocation['height']}"
        c.drawString(margin + 4 * mm, y0 + 8 * mm,
                     _fit_text(head, 11, W - 2 * margin - 8 * mm))
        reason = str(revocation.get("reason") or "").strip()
        c.setFont("Helvetica", 8.5)
        c.drawString(margin + 4 * mm, y0 + 3.6 * mm,
                     _fit_text(("Reason: " + reason) if reason
                               else "No reason was recorded by the issuing side.",
                               8.5, W - 2 * margin - 8 * mm))

    # U19: the chain can be broken while this credential's own block is fine.
    # Printed above the footer, and above the revocation band's baseline so the
    # two never collide.
    if integrity and not integrity.get("ok", True):
        bad = [b for b in (integrity.get("bad_blocks") or []) if isinstance(b, int)]
        where = ("block #" + ", #".join(str(b) for b in bad[:6])) if bad else "unknown block"
        c.setFillColorRGB(0.72, 0.12, 0.12)
        c.setFont("Helvetica-Bold", 7.8)
        c.drawString(margin, L["integrity_main"] * mm,
                     _fit_text(f"CHAIN INTEGRITY FAILED: {where}.", 7.8,
                               W - 2 * margin))
        c.setFont("Helvetica", 7.4)
        c.drawString(margin, L["integrity_note"] * mm,
                     _fit_text("Other blocks on this chain failed to verify; this "
                               "report's verdict may be unreliable. See /healthz.",
                               7.4, W - 2 * margin))

    # footer
    c.setFillColorRGB(0.42, 0.47, 0.53)
    c.setFont("Helvetica", 8)
    if redact:
        c.drawString(margin, L["footer_line1"] * mm,
                     _fit_text("This is a verification report for an on-chain hash. "
                               "Identity fields are withheld.", 8, W - 2 * margin))
        c.drawString(margin, L["footer_line2"] * mm,
                     _fit_text("The credential PDF is issued to its holder through a "
                               "personal link, not to anyone holding the hash.",
                               8, W - 2 * margin))
    else:
        c.drawString(margin, L["footer_line1"] * mm,
                     _fit_text("This PDF carries the exact credential JSON as an "
                               "embedded file.", 8, W - 2 * margin))
        c.drawString(margin, L["footer_line2"] * mm,
                     _fit_text("Upload it to the verification portal for the "
                               "cryptographic verdict — no OCR involved.",
                               8, W - 2 * margin))
    c.showPage()
    c.save()

    if redact:
        return buf.getvalue()

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
        except (OSError, ValueError, TypeError, _PdfReadError) as exc:
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
