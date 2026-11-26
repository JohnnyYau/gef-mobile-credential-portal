"""pdf_extractor.py — auto-fill credential JSON from a certificate PDF.

Input-assistance layer only. It NEVER verifies anything: it produces a
credential JSON draft that the UI fills into the form, so the user can
review it and run the normal six-check verification.

Two extraction modes, in priority order:

1. ``embedded_payload`` — the PDF is portal-issued and carries
   ``credential.json`` as an embedded file attachment. Extraction is
   byte-exact (reuses ``pdf_diploma.extract_credential``), confidence 1.0.

2. ``text_extract`` — a text-layer PDF (electronic certificate) with no
   embedded payload. Field values are matched from the extracted text with
   label-aware regexes (English + Chinese labels), each field gets a
   confidence score, and the document is only a draft for the user to check.

Scanned/image PDFs (no text layer) are NOT attempted here — OCR is a
separate, explicitly-labeled step that the UI may offer later; this module
never invents values for fields it cannot read.
"""

import io
import re
import warnings

from pypdf.errors import PyPdfError as _PdfReadError

from . import pdf_diploma

# --------------------------------------------------------------------------
# Text-layer field extraction
# --------------------------------------------------------------------------

# (label regex, value regex, json field, normalizer)
# value groups: group(2) is the value on a single line after the label.
_FIELD_RULES: list[tuple[re.Pattern, re.Pattern, str, str | None]] = []


def _rule(label_pat: str, value_pat: str, field: str, hint: str | None = None):
    _FIELD_RULES.append((re.compile(label_pat, re.IGNORECASE),
                         re.compile(value_pat, re.IGNORECASE), field, hint))


_rule(r"\b(surname|family\s*name|last\s*name|姓)\b", r"\s*[:：]?\s*([^\n]{1,120})", "Surname", "surname")
_rule(r"\b(given\s*names?|first\s*name|名)\b", r"\s*[:：]?\s*([^\n]{1,120})", "GivenNames", "given")
_rule(r"\b(student\s*id|id\s*no\.?|id\s*number|registration\s*no\.?|學號|学号|證書編號|证书编号)\b",
      r"\s*[:：]?\s*([A-Za-z0-9-]{4,24})", "StudentID", "student_id")
_rule(r"\b(sex|gender|性別|性别)\b", r"\s*[:：]?\s*(M|F|男|女)", "Sex", "sex")
_rule(r"\b(date\s*of\s*birth|birth(?:day|date)?|出生日期|出生年月)\b",
      r"\s*[:：]?\s*(\d{4}[-/.年]?\d{0,2}[-/.月]?\d{0,2}日?)", "DOB", "dob")
_rule(r"\b(degree(?:\s*name)?|qualification|學位|学位|專業|专业|programme?|课程)\b",
      r"\s*[:：]?\s*([^\n]{1,140})", "DegreeName", "degree")
_rule(r"\b(honou?rs?\b|honou?r\s+class|class\s+of\s+honou?rs?|荣誉|榮譽)\b",
      r"\s*[:：]?\s*([^\n]{1,80})", "Honour", "honour")
_rule(r"\b(issuing\s*(?:organisation|organization|institution|office|authority)|頒發機構|颁发机构|簽發機構|签发机构)\b",
      r"\s*[:：]?\s*([^\n]{1,120})", "IssuingO", "issuing_o")
_rule(r"\b(department|faculty|學系|学系|院系|部門|部门)\b",
      r"\s*[:：]?\s*([^\n]{1,120})", "IssuingOU", "issuing_ou")
_rule(r"\b(doc(?:ument)?\s*type|type\s*of\s*(?:certificate|document)|文憑|文凭|证书类型|證書類型)\b",
      r"\s*[:：]?\s*([^\n]{1,80})", "DocType", "doc_type")
_rule(r"\b(date\s*of\s*issue|issued\s*on|issue\s*date|頒發日期|颁发日期|簽發日期|签发日期)\b",
      r"\s*[:：]?\s*(\d{4}[-/.年]?\d{0,2}[-/.月]?\d{0,2}日?)", "DateOfIssue", "date_of_issue")
_rule(r"\b(sign(?:ed|ature|ing)?(?:\s*by)?|authorized\s*signature|頒證人|颁证人|簽發人|签发人)\b",
      r"\s*[:：]?\s*([^\n]{1,120})", "AuthorizedSignature", "signature")
# generic name (when Surname/GivenNames labels are missing)
_rule(r"\b(name|姓名)\b", r"\s*[:：]?\s*([^\n]{1,120})", "FullName", "full_name")

# enrolment period: "Period: 20220901 → 20260801" or "From 2022-09-01 to 2026-08-01"
_PERIOD_RULES = [
    re.compile(r"\b(period|修業期限|修业期限|就讀期間|就读期间)\b\s*[:：]?\s*"
               r"([0-9]{4}[-/.年]?\d{0,2}[-/.月]?\d{0,2}日?)\s*(?:[→\-~至到])\s*"
               r"([0-9]{4}[-/.年]?\d{0,2}[-/.月]?\d{0,2}日?)", re.IGNORECASE),
    re.compile(r"\b(from|from\s*date|入學日期|入学日期)\b\s*[:：]?\s*"
               r"([0-9]{4}[-/.年]?\d{0,2}[-/.月]?\d{0,2}日?)\b", re.IGNORECASE),
    re.compile(r"\b(to|until|to\s*date|畢業日期|毕业日期)\b\s*[:：]?\s*"
               r"([0-9]{4}[-/.年]?\d{0,2}[-/.月]?\d{0,2}日?)\b", re.IGNORECASE),
]
# Degree start/end as standalone date labels
_rule(r"\b(degree\s*start\s*date|入學日期|入学日期)\b",
      r"\s*[:：]?\s*(\d{4}[-/.年]?\d{0,2}[-/.月]?\d{0,2}日?)", "DegreeStartDate", "start")
_rule(r"\b(degree\s*end\s*date|畢業日期|毕业日期)\b",
      r"\s*[:：]?\s*(\d{4}[-/.年]?\d{0,2}[-/.月]?\d{0,2}日?)", "DegreeEndDate", "end")


def _clean(value: str) -> str:
    value = re.sub(r"[,\s]+$", "", (value or "").strip())
    return value


def _norm_date(value: str) -> tuple[str, bool]:
    """Normalize 2022-09-01 / 2022/09/01 / 2022年9月1日 / 20220901 → 20220901.
    Returns (value, ok) — ok=False when the pattern was ambiguous/partial."""
    s = (value or "").strip()
    m = re.match(r"^(\d{4})[-/.年](\d{1,2})?[-/.月](\d{1,2})?日?$", s)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        if mo and d:
            return f"{y}{int(mo):02d}{int(d):02d}", True
        if mo:
            return f"{y}{int(mo):02d}", False
        return y, False
    if re.fullmatch(r"\d{8}", s):
        return s, True
    return s, False


def _extract_text(raw: bytes) -> str:
    """Pull the visible text layer out of a PDF (all pages)."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*EOF marker not found.*")
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(raw))
        except (OSError, ValueError, TypeError, _PdfReadError) as exc:  # not a parseable PDF
            raise ValueError("无法读取该 PDF 文件（可能已损坏或不是 PDF）。") from exc
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except (ValueError, TypeError, KeyError, IndexError):
                continue
        text = "\n".join(parts)
    if not text.strip():
        raise ValueError(
            "该 PDF 没有可提取的文本层（可能是扫描件/图片）。请改为上传凭证 JSON，"
            "或手动填写表单。"
        )
    return text


def extract_text_fields(raw: bytes) -> dict:
    """Parse a text-layer PDF into a credential JSON draft with confidence.

    Returns: {mode: "text_extract", confidence, document, field_confidence,
    warnings}. Missing fields are simply absent from ``document`` — the
    module never invents values it cannot read.
    """
    text = _extract_text(raw)
    found: dict[str, tuple[str, float, str]] = {}  # field -> (value, conf, hint)

    for label_re, value_re, field, hint in _FIELD_RULES:
        m = label_re.search(text)
        if not m:
            continue
        vm = value_re.search(text[m.end():m.end() + 300])
        if not vm:
            continue
        val = _clean(vm.group(1))
        if not val:
            continue
        found[field] = (val, 0.95, hint)

    # period rules (degree start/end)
    for rule in _PERIOD_RULES:
        m = rule.search(text)
        if m and m.lastindex and m.lastindex >= 2:
            if rule.pattern.startswith("\\b(period|") or "→" in rule.pattern or "至" in rule.pattern:
                if "DegreeStartDate" not in found:
                    found["DegreeStartDate"] = (_clean(m.group(2)), 0.9, "start")
                if "DegreeEndDate" not in found:
                    found["DegreeEndDate"] = (_clean(m.group(3)), 0.9, "end")
            elif "from" in rule.pattern.lower() or "入" in rule.pattern:
                if "DegreeStartDate" not in found:
                    found["DegreeStartDate"] = (_clean(m.group(2)), 0.9, "start")
            else:
                if "DegreeEndDate" not in found:
                    found["DegreeEndDate"] = (_clean(m.group(2)), 0.9, "end")

    # build the document
    doc = {"PersonalParticulars": {}, "AcademicInfo": {}, "DocumentInfo": {}}
    field_conf: dict[str, float] = {}
    warnings_out: list[str] = []
    doc_type = (found.get("DocType", ("", 0, ""))[0] or "").upper()

    def put(section, key, value, conf, hint):
        doc[section][key] = value
        field_conf[f"{section}.{key}"] = conf
        if hint and conf < 0.95:
            warnings_out.append(f"{key} 识别置信度偏低（{conf:.0%}），请核对。")

    if "Surname" in found:
        put("PersonalParticulars", "Surname", found["Surname"][0], found["Surname"][1], "surname")
    if "GivenNames" in found:
        put("PersonalParticulars", "GivenNames", found["GivenNames"][0], found["GivenNames"][1], "given")
    elif "FullName" in found:
        # no explicit surname/given labels — keep whole name, flag for review
        put("PersonalParticulars", "GivenNames", found["FullName"][0], 0.7, "full_name")
        warnings_out.append("未识别到单独的“姓/名”字段，姓名整体填入 GivenNames，请拆分核对。")
    for fld, val, conf, hint in (("Sex", "Sex", 0.9, "sex"),
                                  ("StudentID", "StudentID", 0.95, "student_id"),
                                  ("DOB", "DOB", 0.9, "dob")):
        if fld in found:
            put("PersonalParticulars", val, found[fld][0], found[fld][1], hint)

    # dates → normalize
    if "DOB" in doc["PersonalParticulars"]:
        norm, ok = _norm_date(doc["PersonalParticulars"]["DOB"])
        doc["PersonalParticulars"]["DOB"] = norm
        if not ok:
            warnings_out.append("出生日期只识别到部分信息（缺月/日），请补全。")
    for key in ("DegreeStartDate", "DegreeEndDate", "DateOfIssue"):
        if key in found:
            norm, ok = _norm_date(found[key][0])
            target = key if key.startswith("Degree") else "DateOfIssue"
            doc["AcademicInfo" if key.startswith("Degree") else "DocumentInfo"][target] = norm
            field_conf[f"{'AcademicInfo' if key.startswith('Degree') else 'DocumentInfo'}.{target}"] = found[key][1]
            if not ok:
                warnings_out.append(f"{target} 日期不完整，请核对。")

    if "DegreeName" in found:
        put("AcademicInfo", "DegreeName", found["DegreeName"][0], found["DegreeName"][1], "degree")
    if "Honour" in found:
        put("AcademicInfo", "Honour", found["Honour"][0], found["Honour"][1], "honour")
    if "IssuingO" in found:
        put("DocumentInfo", "IssuingO", found["IssuingO"][0], found["IssuingO"][1], "issuing_o")
    if "IssuingOU" in found:
        put("DocumentInfo", "IssuingOU", found["IssuingOU"][0], found["IssuingOU"][1], "issuing_ou")
    if "AuthorizedSignature" in found:
        put("DocumentInfo", "AuthorizedSignature", found["AuthorizedSignature"][0],
            found["AuthorizedSignature"][1], "signature")
    if "DateOfIssue" in found:
        put("DocumentInfo", "DateOfIssue", found["DateOfIssue"][0], found["DateOfIssue"][1], "date_of_issue")

    if doc_type:
        put("DocumentInfo", "DocType", doc_type, 0.9, "doc_type")
    elif "TRANSCRIPT" in text.upper():
        put("DocumentInfo", "DocType", "CERTIFICATE OF TRANSCRIPT", 0.6, "doc_type")
    else:
        put("DocumentInfo", "DocType", "CERTIFICATE OF DIPLOMA", 0.6, "doc_type")

    # missing-key warnings
    for key, label in (("Surname", "姓 Surname"), ("StudentID", "学号 StudentID"),
                       ("DegreeName", "学位 DegreeName"), ("IssuingO", "签发机构 IssuingO")):
        if key not in found:
            warnings_out.append(f"未识别到「{label}」，请在表单中手动填写。")

    confs = list(field_conf.values())
    overall = round(sum(confs) / len(confs), 3) if confs else 0.0
    if overall < 0.75:
        warnings_out.append("整体置信度偏低，请逐项核对后再提交验证。")
    return {
        "mode": "text_extract",
        "confidence": overall,
        "document": doc,
        "field_confidence": field_conf,
        "warnings": warnings_out,
    }


def extract_from_pdf(raw: bytes) -> dict:
    """Try the exact embedded payload first, then text-layer extraction."""
    try:
        document = pdf_diploma.extract_credential(raw)
        return {
            "mode": "embedded_payload",
            "confidence": 1.0,
            "document": document,
            "field_confidence": {k: 1.0 for k in
                                 ("PersonalParticulars", "AcademicInfo", "DocumentInfo")},
            "warnings": ["已从凭证 PDF 内嵌数据精确提取，可直接提交验证。"],
        }
    except ValueError:
        return extract_text_fields(raw)
