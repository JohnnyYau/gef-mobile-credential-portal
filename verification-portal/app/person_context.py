"""person_context.py — resolve "the person in context" from a chat question and
keep lightweight per-session memory so follow-ups ("what degree does he hold?")
stay anchored to the same person.

Privacy rules (batch U5.3: enforced by app/privacy.py, not by convention):
- Profiles returned to the API are MASKED: fields come only from
  ``PRIVACY.fields(section)``; StudentID keeps a 4-char prefix; DOB and the
  other ``NEVER_DISCLOSE`` keys cannot reach a profile at all.
- The chain itself stores hashes only; this module reads the issuer-side
  rawjsondocs index (the same source the RAG corpus is built from).

Session memory lives behind ``app/session_store.py`` (replaceable backend).
"""

import json
import os
import re

from .config import CHAIN_DIR
from .privacy import PRIVACY
from .session_store import open_session_store

_sessions = open_session_store()  # session_id -> {"person": {...}, "name": str}

_ID_RE = re.compile(r"\b(\d{8})\b")
_ANAPHORA_RE = re.compile(
    r"\b(he|she|him|her|his|hers|this person|this student|this graduate|"
    r"this candidate|this applicant|that student|that graduate)\b", re.I)
_WEB_RE = re.compile(
    r"\b(search the web|web search|on the internet|online|in the news|"
    r"news about|public information|public info|background( check)?|"
    r"find online|search for|look up)\b", re.I)


def _raw_documents():
    raw_dir = os.path.join(str(CHAIN_DIR), "rawjsondocs")
    if not os.path.isdir(raw_dir):
        return []
    docs = []
    for fn in sorted(os.listdir(raw_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(raw_dir, fn), encoding="utf-8") as fh:
                docs.append({"hashed_document": fn[:-5], "document": json.load(fh)})
        except (OSError, ValueError):
            continue
    return docs


def _verdict(hashed_document):
    from . import chain_service
    try:
        v = chain_service.verify_hash(hashed_document)
        heights = (v.get("status") or {}).get("issue_heights") or []
        return {"verdict": v.get("verdict", "UNKNOWN"),
                "issued_height": heights[-1] if heights else None}
    except (OSError, ValueError, KeyError, RuntimeError):
        return {"verdict": "UNKNOWN", "issued_height": None}


def _profile(entry):
    d = entry["document"]
    pp = PRIVACY.build("PersonalParticulars", d.get("PersonalParticulars", {}))
    ac = PRIVACY.build("AcademicInfo", d.get("AcademicInfo", {}))
    di = PRIVACY.build("DocumentInfo", d.get("DocumentInfo", {}))
    v = _verdict(entry["hashed_document"])
    profile = {
        "name": f"{pp.get('Surname', '')} {pp.get('GivenNames', '')}".strip(),
        "surname": str(pp.get("Surname", "")),
        "student_id_masked": PRIVACY.mask_student_id(pp.get("StudentID", "")),
        "credential": {
            "doc_type": str(di.get("DocType", "")),
            "degree": str(ac.get("DegreeName", "")),
            "start": str(ac.get("DegreeStartDate", "")),
            "end": str(ac.get("DegreeEndDate", "")),
            "honour": str(ac.get("Honour", "")),
            "issuing_org": str(di.get("IssuingO", "")),
            "issuing_ou": str(di.get("IssuingOU", "")),
            "issued_on": str(di.get("DateOfIssue", "")),
        },
        "verdict": str(v.get("verdict", "UNKNOWN")),
        "issued_height": v.get("issued_height"),
        "hash_prefix": entry["hashed_document"][:12],
        "hashed_document": entry["hashed_document"],  # public on-chain id (QR/verify use it)
    }
    # Cheap last line of defence: build() should already make this impossible.
    PRIVACY.assert_clean(profile, label=f"profile:{entry['hashed_document'][:12]}")
    return profile


def resolve_person(question):
    """Return a masked person profile dict for the person named in the
    question, or None. Exact StudentID wins; otherwise surname / full-name
    match against the issuer-side credential index."""
    docs = _raw_documents()
    if not docs:
        return None
    q = (question or "").lower()
    sid_q = _ID_RE.search(question or "")
    matches = []
    for entry in docs:
        pp = entry["document"].get("PersonalParticulars", {})
        sid = str(pp.get("StudentID", ""))
        surname = str(pp.get("Surname", ""))
        given = str(pp.get("GivenNames", ""))
        full = f"{surname} {given}".strip().lower()
        hit = bool(sid_q and sid == sid_q.group(1)) \
            or (surname.lower() and surname.lower() in q) \
            or (full and full in q)
        if hit:
            matches.append(entry)
    if not matches:
        return None
    # If a person has several credentials, prefer the diploma-style one (it
    # carries DegreeName); the transcript (courses) is the fallback.
    matches.sort(key=lambda e: (
        0 if "DegreeName" in e["document"].get("AcademicInfo", {}) else 1,
        e["hashed_document"]))
    return _profile(matches[0])


def remember(session_id, person):
    if not session_id or not person:
        return
    _sessions.set(session_id, {"person": person, "name": person["name"]})


def context_person(session_id, question):
    """Return the remembered person when the question refers to them
    anaphorically ("he", "his degree", "this student"), else None."""
    if not session_id:
        return None
    entry = _sessions.get(session_id)
    if entry is None:
        return None
    if _ANAPHORA_RE.search(question or ""):
        return entry["person"]
    return None


def wants_web(question, web_flag=False):
    """Web research is explicit: the UI button sets web=True, or the question
    itself asks for public/internet/news information."""
    if web_flag:
        return True
    return bool(_WEB_RE.search(question or ""))


def profile_record(person):
    """A synthetic RAG record so any generator (LLM or offline) can cite the
    masked profile without inventing facts."""
    cred = person["credential"]
    text = (f"Person profile: {person['name']} (student {person['student_id_masked']}) — "
            f"{cred['doc_type']}, {cred['degree']}"
            + (f", {cred['honour']}" if cred.get("honour") else "")
            + f", {cred['start']}–{cred['end']}, issued by {cred['issuing_org']}"
            + (f" / {cred['issuing_ou']}" if cred.get("issuing_ou") else "")
            + f" on {cred['issued_on']}. Status: {person['verdict']}"
            + (f" at height {person['issued_height']}" if person.get("issued_height") else "")
            + f". Hash prefix {person['hash_prefix']}…")
    return {"id": f"person:{person['name']}", "kind": "person_profile",
            "text": text, "score": 2.0}  # pinned above semantic matches
