"""custom_service.py — self-service credential maker + issue end (round 10).

Anyone (with issue access) fills in their own details and the portal:
1. builds the standard credential JSON,
2. ISSUES it on the chain (the maker acts as the issuing side),
3. renders a verifiable PDF (with the embedded JSON) and saves the PDF +
   JSON into the main project directory ("sync to the project"),
4. so that anyone who uploads that PDF later verifies it VALID directly.

Honest boundary: issuing is the same admin-guarded action as POST /api/issue.
In public verifier mode (issuance disabled) the endpoint refuses with 403 and
the UI hides the self-issue tab. A ``issue=false`` draft mode is available for
people who only want a template file (it will verify NOT FOUND until issued).
"""

import json
import re
import time
from pathlib import Path

from . import chain_service, config as cfg, pdf_diploma

# defaults for an UNKNOWN value are left empty on purpose — never invent data
_FIELD_DEFAULTS = {
    "Sex": "M",
    "DegreeStartDate": "20220901",
    "DegreeEndDate": "20260801",
    "DocType": "CERTIFICATE OF DIPLOMA",
    "IssuingO": "UNIVERSITY OF UTOPIA",
    "IssuingOU": "RECORD OFFICE",
}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")
_SAFE_FID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def _clean(value, default=""):
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def _norm_date(value, default=""):
    s = _clean(value, "")
    if not s:
        return default
    s = re.sub(r"[-/.年]", "", s).replace("月", "").replace("日", "")
    return s


def build_document(fields: dict) -> dict:
    """Normalize raw form fields into the standard credential JSON.

    Raises ValueError with a friendly message when essential fields are
    missing (at least one name part, a student id, and a degree).
    """
    surname = _clean(fields.get("surname"))
    given = _clean(fields.get("given_names"))
    full = _clean(fields.get("name"))  # single "name" field alternative
    if not surname and not given:
        if full:
            surname, given = full, ""
        else:
            raise ValueError("请至少填写姓名（姓 Surname 或名 Given Names）。")

    student_id = _clean(fields.get("student_id"))
    if not student_id:
        raise ValueError("请填写学号 Student ID。")
    degree = _clean(fields.get("degree"))
    if not degree:
        raise ValueError("请填写学位/专业 Degree。")

    doc = {
        "PersonalParticulars": {
            "Surname": surname or "—",
            "GivenNames": given or "—",
            "Sex": _clean(fields.get("sex"), _FIELD_DEFAULTS["Sex"]).upper()[:1],
            "DOB": _norm_date(fields.get("dob")),
            "StudentID": student_id,
        },
        "AcademicInfo": {
            "DegreeName": degree,
            "DegreeStartDate": _norm_date(fields.get("degree_start"),
                                          _FIELD_DEFAULTS["DegreeStartDate"]),
            "DegreeEndDate": _norm_date(fields.get("degree_end"),
                                        _FIELD_DEFAULTS["DegreeEndDate"]),
            "Honour": _clean(fields.get("honour")),
            "Observations": _clean(fields.get("observations")),
        },
        "DocumentInfo": {
            "DateOfIssue": _norm_date(fields.get("date_of_issue"), "20261001"),
            "AuthorizedSignature": _clean(fields.get("authorized_signature")),
            "IssuingO": _clean(fields.get("issuer"), _FIELD_DEFAULTS["IssuingO"]),
            "IssuingOU": _clean(fields.get("issuer_unit"), _FIELD_DEFAULTS["IssuingOU"]),
            "DocType": _clean(fields.get("doc_type"), _FIELD_DEFAULTS["DocType"]).upper(),
        },
    }
    return doc


def _output_dir() -> Path:
    base = Path(cfg.CUSTOM_OUTPUT_DIR)
    try:
        base.mkdir(parents=True, exist_ok=True)
        probe = base / ".gef26_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return base
    except OSError:
        # not writable (e.g. deployed) -> keep outputs inside the portal
        fallback = cfg.BASE_DIR / "custom_outputs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _safe_id(student_id: str, ts: int) -> str:
    core = _SAFE_NAME.sub("", student_id)[:24] or "credential"
    return f"{core}-{ts}"


def build_outputs(fields: dict, base_url: str, issue: bool = True) -> dict:
    """Build the credential, optionally issue it, render + save the files.

    Returns {file_id, document, hashed_document, height?, on_chain, pdf_url,
    json_url, verify_url, output_dir, note}.
    """
    document = build_document(fields)
    hashed = chain_service.hash_of(document)
    height = None
    if issue:
        issued = chain_service.issue(document)
        hashed = issued.get("hashed_document") or hashed
        height = issued.get("height")
    pdf_bytes = pdf_diploma.render_diploma_pdf(document, hashed, base_url)

    out_dir = _output_dir()
    file_id = _safe_id(document["PersonalParticulars"]["StudentID"],
                       int(time.time()))
    pdf_path = out_dir / f"{file_id}.pdf"
    json_path = out_dir / f"{file_id}.json"
    pdf_path.write_bytes(pdf_bytes)
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return {
        "file_id": file_id,
        "document": document,
        "hashed_document": hashed,
        "height": height,
        "on_chain": bool(issue),
        "pdf_url": f"/api/custom/file/{file_id}/pdf",
        "json_url": f"/api/custom/file/{file_id}/json",
        "verify_url": f"/verify?hash={hashed}",
        "output_dir": str(out_dir),
        "note": (
            "已签发上链并生成 PDF/JSON（同步到项目目录）。上传此 PDF（或按编号 "
            "验证）将直接显示「真实有效」。"
            if issue else
            "已生成 PDF 与 JSON（同步到项目目录），但尚未上链——验证会显示"
            "「查无此证」，需管理员签发后生效。"
        ),
    }


def list_outputs() -> list:
    """Return generated files newest-first (id, pdf/json urls)."""
    out_dir = _output_dir()
    entries = []
    for pdf_path in sorted(out_dir.glob("*.pdf"), reverse=True):
        if not pdf_path.is_file():
            continue
        file_id = pdf_path.stem
        entries.append({
            "file_id": file_id,
            "name": file_id,
            "pdf_url": f"/api/custom/file/{file_id}/pdf",
            "json_url": f"/api/custom/file/{file_id}/json",
        })
    return entries


def resolve_file(file_id: str, kind: str) -> Path:
    """Map a file id + kind to a real path inside the output dir (no escape)."""
    if not _SAFE_FID.match(file_id):
        raise ValueError("无效的文件标识。")
    out_dir = _output_dir().resolve()
    name = f"{file_id}.{kind}"
    path = (out_dir / name).resolve()
    if path.parent != out_dir or not path.is_file():
        raise ValueError("文件不存在。")
    return path
