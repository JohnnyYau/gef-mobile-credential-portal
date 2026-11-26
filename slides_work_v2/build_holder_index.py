"""One-shot: build PII-free holder_index rows from existing rawjsondocs.

U12 R5. The raw documents stay where they are (RAG, PDF, disclosure), but the
shipped bundle must not carry them. This derives the lookup rows the holder
flow actually needs: StudentID, hash, type, degree — no name, no DOB, no
e-mail.
"""
import json
import sys
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent / "verification-portal"
sys.path.insert(0, str(PORTAL))

CHAIN = PORTAL / "data" / "demo-chain"
RAW = CHAIN / "rawjsondocs"
INDEX = CHAIN / "holder_index"


def main():
    if not RAW.exists():
        print(f"no raw dir at {RAW}")
        return 1
    INDEX.mkdir(parents=True, exist_ok=True)
    built = skipped = 0
    for f in sorted(RAW.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"  [skip unreadable] {f.name}: {exc}")
            skipped += 1
            continue
        pp = doc.get("PersonalParticulars") or {}
        sid = str(pp.get("StudentID") or "")
        if not sid:
            print(f"  [skip no sid] {f.name}")
            skipped += 1
            continue
        row = {
            "sid": sid,
            "hashed_document": f.stem,
            "doc_type": (doc.get("DocumentInfo") or {}).get("DocType") or "CREDENTIAL",
            "degree": (doc.get("AcademicInfo") or {}).get("DegreeName") or "—",
        }
        target = INDEX / f"{f.stem}.json"
        if target.exists():
            skipped += 1
            continue
        target.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        built += 1
    print(f"raw {len(list(RAW.glob('*.json')))}  built {built}  skipped {skipped}")
    print(f"index rows now: {len(list(INDEX.glob('*.json')))}")
    # sanity: no PII keys in what we just wrote
    bad = []
    for f in INDEX.glob("*.json"):
        text = f.read_text(encoding="utf-8")
        if any(k in text for k in ('"Email"', '"DOB"', '"Name"', '"MobileNo"')):
            bad.append(f.name)
    print("pii hits:", bad if bad else "none")
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(main())
