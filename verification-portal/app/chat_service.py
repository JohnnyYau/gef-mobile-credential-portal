"""chat_service.py — RAG chat orchestration: retrieve -> generate -> sources."""

import json
import logging
import os

from . import chain_service, person_context, web_research
from .config import CHAIN_DIR
from .rag_generator import backend_status, generate
from .rag_indexer import credential_entry, get_index

logger = logging.getLogger("chat")

MAX_QUESTION_LEN = 500

SUGGESTIONS = [
    "Has CHAN TAI MAN's diploma been revoked?",
    "Tell me about CHAN TAI MAN",
    "Search the web for CHAN TAI MAN",
    "Is the transcript for StudentID 22000000 still valid?",
    "Who is the trusted signer of this chain?",
    "What is in the latest block?",
]


def _exact_credential_record(question):
    """Exact lookup of a credential by hash / StudentID / person name in the
    question, scanning rawjsondocs. Numeric IDs and names are exact-match
    features — semantic retrieval can miss them, so they are pinned first."""
    q = question.lower()
    raw_dir = os.path.join(str(CHAIN_DIR), "rawjsondocs")
    if not os.path.isdir(raw_dir):
        return None
    for filename in sorted(os.listdir(raw_dir)):
        if not filename.endswith(".json"):
            continue
        hashed_document = filename[:-5]
        try:
            with open(os.path.join(raw_dir, filename), encoding="utf-8") as fh:
                document = json.load(fh)
        except (OSError, ValueError):
            continue
        pp = document.get("PersonalParticulars", {})
        sid = str(pp.get("StudentID", ""))
        name = " ".join(x for x in (pp.get("GivenNames", ""), pp.get("Surname", "")) if x)
        if hashed_document in question or (sid and sid in q) or (name and name.lower() in q):
            return credential_entry(document, hashed_document)
    return None


def answer(question, session_id=None, web=False):
    """Answer a natural-language question with sources from the chain.

    Adds "the person in context": if the question names a person (or refers
    anaphorically to a remembered one), a masked profile is resolved and
    returned as ``person``. If web research is requested (button or explicit
    web keywords) and a person is known, ``web`` carries the public-source
    results (or an honest unavailable reason).
    """
    question = (question or "").strip()[:MAX_QUESTION_LEN]
    if not question:
        raise ValueError("Question is empty.")

    chain_service.ensure_chain()

    # --- person in context ---
    person = person_context.resolve_person(question)
    if person is None and session_id:
        person = person_context.context_person(session_id, question)
    if person:
        person_context.remember(session_id, person)

    index = get_index()
    records = index.search(question, k=6)

    # Pin an exact identifier match (hash / student ID / name) to the top of
    # the retrieved records so citations are real and answers are exact.
    exact = _exact_credential_record(question)
    if exact and not any(r["id"] == exact["id"] for r in records):
        records.insert(0, exact)
    # Person-in-context: give any generator the masked profile to cite, and
    # pin the SAME credential the profile resolved to (so the answer and the
    # profile card always agree on height/hash).
    if person and not any(r.get("kind") == "person_profile" for r in records):
        records.insert(0, person_context.profile_record(person))
    if person and person.get("hashed_document"):
        rec = next((r for r in records
                    if r.get("hashed_document") == person["hashed_document"]), None)
        if rec and records[0] is not rec:
            records = [r for r in records if r["id"] != rec["id"]]
            records.insert(1, rec)  # after the profile record

    result = generate(question, records, str(CHAIN_DIR))

    cited = result.get("citations") or []
    sources_are_fallback = not cited
    if sources_are_fallback:  # safety: never show an answer with zero sources
        cited = list(range(1, len(records) + 1))
    sources = []
    for i in cited:
        if 1 <= i <= len(records):
            sources.append(_source_view(records[i - 1]))
    # person-in-context: always back the profile card with its masked record
    if person and not any(s.get("kind") == "person_profile" for s in sources):
        sources.insert(0, _source_view(person_context.profile_record(person)))

    validation = result.get("validation") or {}
    response = {
        "question": question,
        "answer": result["answer"],
        "sources": sources,
        "generator": result["backend"],
        "model": result.get("model"),
        "person": person,
        "retrieval": {
            "hits": len(records),
            "top_score": records[0].get("score") if records else None,
            "embedder": index.stats()["embedder"],
        },
        # U5.2: make the generation contract observable instead of implied.
        # ``sources_are_fallback`` is true when the answer cited nothing and we
        # showed every retrieved record; the UI can label those as "context",
        # not as sources the answer actually used.
        "generation": {
            "degraded": result.get("degraded") or [],
            "validation_ok": validation.get("ok"),
            "problems": validation.get("problems") or [],
            "sources_are_fallback": sources_are_fallback,
        },
    }

    # --- web research for the person in context ---
    if person and person_context.wants_web(question, web):
        web_obj = web_research.search_person(
            person["name"], person["credential"]["issuing_org"])
        response["web"] = web_obj
        if web_obj.get("status") == "ok":
            response["answer"] += (
                f"\n\n[Web research] {len(web_obj['sources'])} public source(s) "
                f"found for {person['name']} — see the web card."
                + (" (demo fixture, not real public sources)" if web_obj.get("demo") else ""))
        else:
            response["answer"] += (
                f"\n\n[Web research] unavailable: "
                f"{web_obj.get('reason') or 'no public sources found'}.")
    else:
        response["web"] = None

    return response


def rag_status():
    """Report which embedder + generator are active."""
    chain_service.ensure_chain()
    index = get_index()
    stats = index.stats()
    return {
        "embedder": stats["embedder"],
        "embedding_dim": stats["dim"],
        "index_entries": stats["entries"],
        "generator": backend_status(),
        "suggestions": SUGGESTIONS,
    }


def _source_view(record):
    view = {
        "id": record["id"],
        "kind": record.get("kind"),
        "text": record["text"],
        "score": record.get("score"),
    }
    for key in ("height", "action", "hashed_document"):
        if record.get(key):
            view[key] = record[key]
    return view
