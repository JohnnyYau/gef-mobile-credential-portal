"""rag_generator.py — answer generation for the RAG chat.

Three backends, in priority order:
  1. DeepSeek API   — used when DEEPSEEK_API_KEY is set.
  2. Ollama         — used when OLLAMA_BASE_URL is set (e.g. qwen2.5:3b).
  3. Offline engine — always available: deterministic answers over the
                      retrieved records + live chain state, with citations.
                      No API key, no hallucination, ideal for demos.

Batch U5.2: the offline engine is a rule *table* (``OFFLINE_RULES``) rather than
an if/elif ladder, generated answers get a structural check, and a failing
backend degrades to the next one instead of straight to offline.
"""

import logging
import os
import re

import httpx

from . import blockchain_util
from .config import (
    CHAIN_DIR,
    LLM_DEEPSEEK_TIMEOUT,
    LLM_OLLAMA_TIMEOUT,
    RAG_CITATION_LIMIT,
)
from .errors import UnavailableBackendError

logger = logging.getLogger("rag")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or None
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com/chat/completions")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL") or None
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

SYSTEM_PROMPT = (
    "You are a credential-verification assistant for a university diploma "
    "blockchain. Answer the user's question using ONLY the numbered context "
    "records provided. Cite records inline as [1], [2], etc. when you use "
    "them. Be precise: state whether a credential is valid, revoked, or not "
    "found, and at which block height it was issued or revoked. If the "
    "context does not contain the answer, say explicitly that you cannot "
    "answer from the records. Do not invent facts."
)


def _numbered_context(records):
    return "\n".join(f"[{i}] {r['text']}" for i, r in enumerate(records, 1))


def _chat_messages(question, records):
    user = f"Context records:\n{_numbered_context(records)}\n\nQuestion: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# --------------------------------------------------------------------------
# LLM backends
# --------------------------------------------------------------------------


def _deepseek(question, records):
    messages = _chat_messages(question, records)
    try:
        with httpx.Client(timeout=LLM_DEEPSEEK_TIMEOUT) as client:
            response = client.post(
                DEEPSEEK_BASE,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 500,
                },
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        # U10: "configured but unreachable" is a domain condition, not an
        # anonymous network error; the caller still degrades to the next
        # backend, so the HTTP contract does not change.
        raise UnavailableBackendError(
            f"deepseek at {DEEPSEEK_BASE} did not answer: {type(exc).__name__}"
        ) from exc
    return answer, DEEPSEEK_MODEL


def _ollama(question, records):
    base = OLLAMA_BASE_URL.rstrip("/")
    messages = _chat_messages(question, records)
    try:
        with httpx.Client(timeout=LLM_OLLAMA_TIMEOUT) as client:
            response = client.post(
                f"{base}/api/chat",
                json={"model": OLLAMA_MODEL, "messages": messages,
                      "stream": False},
            )
            response.raise_for_status()
            answer = response.json()["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise UnavailableBackendError(
            f"ollama at {base} did not answer: {type(exc).__name__}"
        ) from exc
    return answer, OLLAMA_MODEL


# --------------------------------------------------------------------------
# Offline engine (deterministic, no LLM)
# --------------------------------------------------------------------------


def _status_line(chain, hashed_document, record, label):
    status = blockchain_util.fetch_status(chain, hashed_document)
    if status["revoked"]:
        line = (f"{label} (hash {hashed_document[:24]}...) was REVOKED"
                f" at height {status['revoke_heights'][-1]}"
                f" (issued at height {status['issue_heights'][-1]} if any).")
    elif status["issued"]:
        line = (f"{label} (hash {hashed_document[:24]}...) is VALID on the chain"
                f" — issued at height {status['issue_heights'][-1]}, not revoked.")
    else:
        line = (f"{label} (hash {hashed_document[:24]}...) is NOT FOUND — "
                f"no ISSUE block records this document.")
    return line


# -- rule handlers: (lowered_question, records, original_question, chain) ----

def _r_hash(q, records, question, chain):
    for i, r in enumerate(records, 1):
        h = r.get("hashed_document")
        if h and h in question:
            label = ("The credential" if r["kind"] == "credential"
                     else f"The document referenced by block {r['id']}")
            return _status_line(chain, h, r, label), [i]
    return None


def _r_courses(q, records, question, chain):
    for i, r in enumerate(records, 1):
        if r["kind"] == "credential" and "courses:" in r.get("text", ""):
            snippet = r["text"].split("courses:", 1)[1].split("document type", 1)[0].strip()
            who = r.get("person_name") or "the student"
            return f"The transcript of {who} lists: {snippet}.", [i]
    return None


def _r_person(q, records, question, chain):
    for i, r in enumerate(records, 1):
        if r["kind"] != "credential":
            continue
        surname = (r.get("surname") or "").lower()
        given = (r.get("given_names") or "").lower()
        sid = str(r.get("student_id") or "")
        name = (r.get("person_name") or "").lower()
        hit = bool(name and name in q) or bool(surname and surname in q) \
            or bool(given and given in q) or bool(sid and sid in q)
        if hit:
            label = (f"The credential of {r.get('person_name')}"
                     if r.get("person_name")
                     else f"StudentID {r.get('student_id')}")
            return _status_line(chain, r["hashed_document"], r, label), [i]
    return None


def _r_unknown_sid(q, records, question, chain):
    sid_q = re.search(r"\b\d{8}\b", q)
    if sid_q:
        return (f"No credential is recorded for student ID {sid_q.group(0)} "
                f"on this chain."), []
    return None


def _chain_cite(records):
    """Index of the chain-level record in ``records``, or [] if absent.

    Chain-wide answers (signer, count, integrity, algorithm, revocations) used
    to return a hardcoded ``[1]``. That was only correct when record 1 happened
    to be ``chain:info``; when retrieval ranked a credential first, the answer
    cited an unrelated credential — the QA golden set (U5.4) caught it.
    """
    for i, r in enumerate(records, 1):
        if r.get("kind") == "chain" or str(r.get("id", "")).startswith("chain:"):
            return [i]
    return []


def _r_revocations(q, records, question, chain):
    revoked = []
    for h in range(1, blockchain_util.last_height(chain) + 1):
        payload = blockchain_util.load_block(chain, h).get("payload", {})
        if payload.get("action") == "REVOKE":
            revoked.append(payload.get("HashedDocument"))
    if revoked:
        short = ", ".join(h[:16] + "..." for h in revoked)
        return (f"The chain contains {len(revoked)} revocation(s): {short}. "
                f"Ask about a specific hash, student ID or name for details."), _chain_cite(records)
    return "No credentials are revoked on this chain.", _chain_cite(records)


def _r_count(q, records, question, chain):
    height = blockchain_util.last_height(chain)
    issue = revoke = 0
    for h in range(1, height + 1):
        action = blockchain_util.load_block(chain, h).get("payload", {}).get("action")
        if action == "ISSUE":
            issue += 1
        elif action == "REVOKE":
            revoke += 1
    raw_dir = os.path.join(chain, "rawjsondocs")
    creds = len([f for f in os.listdir(raw_dir) if f.endswith(".json")]) \
        if os.path.isdir(raw_dir) else 0
    answer = (f"On this chain: {height} blocks in total "
              f"({issue} ISSUE, {revoke} REVOKE), "
              f"and {creds} credential document(s) indexed.")
    return answer, _chain_cite(records)


def _r_signer(q, records, question, chain):
    info = blockchain_util.read_info(chain)
    signers = info.get("trusted_signers", [])
    if not signers:
        return "No trusted data signer is registered on this chain.", _chain_cite(records)
    lines = [
        f"Trusted data signer(s): {s['name']} ({s['ds_algo']}, "
        f"sha256 fingerprint {s['sha256fgpt'][:24]}...) " for s in signers
    ]
    return "\n".join(line.strip() for line in lines), _chain_cite(records)


def _r_algorithm(q, records, question, chain):
    info = blockchain_util.read_info(chain)
    return (f"The chain uses content hash algorithm "
            f"{info.get('content_hash_algo')} (RFC 8785 canonical JSON, "
            f"base64url digests, Merkle-rooted document hashes)."), _chain_cite(records)


def _r_integrity(q, records, question, chain):
    ok, report = blockchain_util.verify_chain(chain)
    problems = sum(1 for r in report if not r["ok"])
    if ok:
        return (f"Chain integrity is OK: all {len(report)} blocks verify "
                f"from genesis (hashes, prevHashSum links, heights, "
                f"signatures)."), _chain_cite(records)
    return (f"Chain integrity is BROKEN: {problems} of {len(report)} "
            f"blocks failed verification. Tampering was detected."), _chain_cite(records)


def _r_latest(q, records, question, chain):
    height = blockchain_util.last_height(chain)
    block = blockchain_util.load_block(chain, height)
    action = block.get("payload", {}).get("action")
    hdoc = block.get("payload", {}).get("HashedDocument", "")
    answer = (f"The latest block is height {height}, action {action}"
              + (f", document hash {hdoc[:24]}..." if hdoc else "") + ".")
    cited = [1]
    for i, r in enumerate(records, 1):
        if r.get("height") == height:
            cited = [i]
            break
    return answer, cited


def _r_summary(q, records, question, chain):
    if records:
        shown = records[:RAG_CITATION_LIMIT]
        lines = [f"I found {len(records)} relevant record(s) on the chain."]
        for r in shown:
            lines.append(f"- {r['text']}")
        lines.append("Ask for a specific credential (name, student ID or hash) "
                     "to get its validity status.")
        return "\n".join(lines), list(range(1, len(shown) + 1))
    return "No records matched. The chain may be empty.", []


def _has_signer_word(q):
    return any(word in q for word in ("signer", "issuer", "who issued",
                                      "university", "registered key"))


def _has_count_word(q):
    return any(word in q for word in ("how many", "number of", "count "))


def _has_integrity_word(q):
    return "integrity" in q or ("chain" in q and any(
        w in q for w in ("valid", "corrupt", "tamper", "intact", "ok",
                         "broken", "check")))


# Ordered rule table. First entry whose ``match`` returns True answers, and a
# handler returning None means "not mine after all" and the scan continues.
# Order matters: a hash mentioned in the question beats every keyword match,
# because a literal 88-char hash is the strongest possible signal.
OFFLINE_RULES = [
    {"name": "exact-hash", "match": lambda q, r, s: True, "answer": _r_hash},
    {"name": "courses", "match": lambda q, r, s: "course" in q, "answer": _r_courses},
    {"name": "person-or-sid", "match": lambda q, r, s: any(
        x["kind"] == "credential" for x in r), "answer": _r_person},
    {"name": "unknown-sid", "match": lambda q, r, s: bool(re.search(r"\b\d{8}\b", q)),
     "answer": _r_unknown_sid},
    {"name": "revocations", "match": lambda q, r, s: "revok" in q,
     "answer": _r_revocations},
    {"name": "counting", "match": lambda q, r, s: _has_count_word(q),
     "answer": _r_count},
    {"name": "signer", "match": lambda q, r, s: _has_signer_word(q),
     "answer": _r_signer},
    {"name": "algorithm", "match": lambda q, r, s: "algorithm" in q
     or "algo " in q or q.endswith("algo"), "answer": _r_algorithm},
    {"name": "integrity", "match": lambda q, r, s: _has_integrity_word(q),
     "answer": _r_integrity},
    {"name": "latest-block", "match": lambda q, r, s: any(
        w in q for w in ("latest", "last block", "most recent", "newest")),
     "answer": _r_latest},
    {"name": "summary", "match": lambda q, r, s: True, "answer": _r_summary},
]


def _offline(question, records, chain):
    """Run the ordered rule table; first rule that answers wins."""
    q = question.lower()
    for rule in OFFLINE_RULES:
        if not rule["match"](q, records, question):
            continue
        result = rule["answer"](q, records, question, chain)
        if result is not None:
            return result
    return "No records matched. The chain may be empty.", []


def offline_rule_names():
    """The table's rule names in priority order (for tests and diagnostics)."""
    return [rule["name"] for rule in OFFLINE_RULES]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def generate(question, records, chain=None):
    """Return {answer, backend, model, citations, degraded, validation}.

    Backend order (batch U5.2): DeepSeek -> Ollama -> offline. A failure is not
    fatal and not silent: each attempt that fails is recorded in ``degraded`` so
    the caller can tell "answered offline because nothing was configured" from
    "answered offline because the configured backend was unreachable".
    """
    chain = chain or str(CHAIN_DIR)
    backend = "offline"
    model = None
    answer = None
    citations = []
    degraded: list[str] = []

    if DEEPSEEK_API_KEY:
        try:
            answer, model = _deepseek(question, records)
            backend = "deepseek"
        except UnavailableBackendError as exc:
            degraded.append(f"deepseek unavailable: {exc}")
            logger.warning("DeepSeek call failed (%s); trying next backend", exc)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            degraded.append(f"deepseek unavailable: {type(exc).__name__}")
            logger.warning("DeepSeek call failed (%s); trying next backend", exc)

    if answer is None and OLLAMA_BASE_URL:
        try:
            answer, model = _ollama(question, records)
            backend = "ollama"
        except UnavailableBackendError as exc:
            degraded.append(f"ollama unavailable: {exc}")
            logger.warning("Ollama call failed (%s); falling back to offline", exc)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            degraded.append(f"ollama unavailable: {type(exc).__name__}")
            logger.warning("Ollama call failed (%s); falling back to offline", exc)

    if answer is None:
        answer, citations = _offline(question, records, chain)
        backend = "offline"

    if backend in ("deepseek", "ollama"):
        # Prefer the citations the model actually wrote; only when it wrote
        # none do we fall back to "it saw every record". Filling in all
        # records unconditionally would make the structural check below
        # vacuous — the generator would be certifying its own citations.
        parsed = extract_citations(answer)
        citations = parsed or list(range(1, len(records) + 1))

    validation = validate_answer(answer, citations, len(records))
    if not validation["ok"] and backend != "offline":
        # An empty (or citation-fabricating) LLM answer is worse than a
        # deterministic one: use the offline engine instead.
        degraded.append("LLM answer failed structural validation; used offline")
        answer, citations = _offline(question, records, chain)
        backend = "offline"
        model = None
        validation = validate_answer(answer, citations, len(records))

    return {
        "answer": answer,
        "backend": backend,
        "model": model,
        "citations": validation["citations"],
        "degraded": degraded,
        "validation": validation,
    }


def extract_citations(text):
    """Inline ``[n]`` citation numbers in an answer, in order, deduplicated."""
    seen: list[int] = []
    for n in re.findall(r"\[(\d+)\]", text or ""):
        num = int(n)
        if num not in seen:
            seen.append(num)
    return seen


def validate_answer(answer, citations, record_count):
    """Structural checks on a generated answer (batch U5.2).

    Rules:
      * the answer must be non-empty text;
      * every citation must address a record that was actually returned
        (1..record_count) — an out-of-range [7] when 3 records were sent is a
        fabricated citation;
      * zero citations is allowed and flagged, not "fixed": inventing a source
        to satisfy a rule would be worse than admitting the answer is unsourced.
    """
    problems: list[str] = []
    text = (answer or "").strip()
    if not text:
        problems.append("answer is empty")

    valid: list[int] = []
    bad_citation = False
    for c in citations or []:
        try:
            n = int(c)
        except (TypeError, ValueError):
            problems.append(f"citation {c!r} is not an integer")
            bad_citation = True
            continue
        if n < 1 or n > record_count:
            problems.append(
                f"citation [{n}] is outside the {record_count} returned record(s)")
            bad_citation = True
            continue
        if n not in valid:
            valid.append(n)

    if not valid:
        problems.append("answer cites no record")

    return {
        "ok": bool(text) and not bad_citation,
        "citations": valid,
        "problems": problems,
        "citation_count": len(valid),
        "record_count": record_count,
        "zero_citations": not valid,
    }


def backend_status():
    """Human-readable description of which generator is active."""
    if DEEPSEEK_API_KEY:
        return f"DeepSeek ({DEEPSEEK_MODEL})"
    if OLLAMA_BASE_URL:
        return f"Ollama ({OLLAMA_MODEL})"
    return "offline engine (no API key configured)"
