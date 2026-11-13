"""rag_generator.py — answer generation for the RAG chat.

Three backends, in priority order:
  1. DeepSeek API   — used when DEEPSEEK_API_KEY is set.
  2. Ollama         — used when OLLAMA_BASE_URL is set (e.g. qwen2.5:3b).
  3. Offline engine — always available: deterministic answers over the
                      retrieved records + live chain state, with citations.
                      No API key, no hallucination, ideal for demos.
"""

import logging
import os
import re

import httpx

from . import blockchain_util
from .config import CHAIN_DIR

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
    with httpx.Client(timeout=40) as client:
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
    return answer, DEEPSEEK_MODEL


def _ollama(question, records):
    base = OLLAMA_BASE_URL.rstrip("/")
    messages = _chat_messages(question, records)
    with httpx.Client(timeout=90) as client:
        response = client.post(
            f"{base}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
        )
        response.raise_for_status()
        answer = response.json()["message"]["content"].strip()
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


def _offline(question, records, chain):
    q = question.lower()
    cited = []

    # 1. exact hash mentioned in the question
    for i, r in enumerate(records, 1):
        h = r.get("hashed_document")
        if h and h in question:
            cited.append(i)
            label = ("The credential" if r["kind"] == "credential"
                     else f"The document referenced by block {r['id']}")
            return _status_line(chain, h, r, label), cited

    # 1.5 courses question — list the courses before answering status
    if "course" in q:
        for i, r in enumerate(records, 1):
            if r["kind"] == "credential" and "courses:" in r.get("text", ""):
                snippet = r["text"].split("courses:", 1)[1].split("document type", 1)[0].strip()
                who = r.get("person_name") or "the student"
                return (f"The transcript of {who} lists: {snippet}."), [i]

    # 2. person / student-id match in credential records (order-insensitive)
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
            cited.append(i)
            label = f"The credential of {r.get('person_name')}" if r.get("person_name") \
                else f"StudentID {r.get('student_id')}"
            return _status_line(chain, r["hashed_document"], r, label), cited

    # 2.4 student-ID existence question without a match
    sid_q = re.search(r"\b\d{8}\b", q)
    if sid_q:
        return (f"No credential is recorded for student ID {sid_q.group(0)} "
                f"on this chain."), []

    # 2.5 revocation status question without a specific credential
    if "revok" in q:
        revoked = []
        for h in range(1, blockchain_util.last_height(chain) + 1):
            payload = blockchain_util.load_block(chain, h).get("payload", {})
            if payload.get("action") == "REVOKE":
                revoked.append(payload.get("HashedDocument"))
        if revoked:
            short = ", ".join(h[:16] + "..." for h in revoked)
            return (f"The chain contains {len(revoked)} revocation(s): {short}. "
                    f"Ask about a specific hash, student ID or name for details."), [1]
        return "No credentials are revoked on this chain.", [1]

    # 3. counting
    if any(word in q for word in ("how many", "number of", "count ")):
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
        cited = [1]
        return answer, cited

    # 4. signer / issuer questions
    if any(word in q for word in ("signer", "issuer", "who issued", "university",
                                  "registered key")):
        info = blockchain_util.read_info(chain)
        signers = info.get("trusted_signers", [])
        if not signers:
            return "No trusted data signer is registered on this chain.", [1]
        lines = [
            f"Trusted data signer(s): {s['name']} ({s['ds_algo']}, "
            f"sha256 fingerprint {s['sha256fgpt'][:24]}...)" for s in signers
        ]
        return "\n".join(lines), [1]

    # 4.5 hash algorithm question
    if "algorithm" in q or "algo " in q or q.endswith("algo"):
        info = blockchain_util.read_info(chain)
        return (f"The chain uses content hash algorithm "
                f"{info.get('content_hash_algo')} (RFC 8785 canonical JSON, "
                f"base64url digests, Merkle-rooted document hashes)."), [1]

    # 5. chain integrity / tamper
    if "integrity" in q or ("chain" in q and any(w in q for w in
                            ("valid", "corrupt", "tamper", "intact", "ok",
                             "broken", "check"))):
        ok, report = blockchain_util.verify_chain(chain)
        problems = sum(1 for r in report if not r["ok"])
        if ok:
            return (f"Chain integrity is OK: all {len(report)} blocks verify "
                    f"from genesis (hashes, prevHashSum links, heights, "
                    f"signatures)."), [1]
        return (f"Chain integrity is BROKEN: {problems} of {len(report)} "
                f"blocks failed verification. Tampering was detected."), [1]

    # 6. latest / recent blocks
    if any(w in q for w in ("latest", "last block", "most recent", "newest")):
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

    # 7. generic summary of what was found
    if records:
        shown = records[:3]
        lines = [f"I found {len(records)} relevant record(s) on the chain."]
        for r in shown:
            lines.append(f"- {r['text']}")
        lines.append("Ask for a specific credential (name, student ID or hash) "
                     "to get its validity status.")
        return "\n".join(lines), list(range(1, len(shown) + 1))
    return "No records matched. The chain may be empty.", []


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def generate(question, records, chain=None):
    """Return {answer, backend, model, citations}."""
    chain = chain or str(CHAIN_DIR)
    backend = "offline"
    model = None
    answer = None
    citations = []

    if DEEPSEEK_API_KEY:
        try:
            answer, model = _deepseek(question, records)
            backend = "deepseek"
        except Exception as exc:  # noqa: BLE001 — fall back to offline
            logger.warning("DeepSeek call failed (%s); falling back to offline", exc)
    elif OLLAMA_BASE_URL:
        try:
            answer, model = _ollama(question, records)
            backend = "ollama"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama call failed (%s); falling back to offline", exc)

    if answer is None:
        answer, citations = _offline(question, records, chain)
        backend = "offline"

    if backend in ("deepseek", "ollama"):
        # LLM answers were shown every record — cite them all in the UI
        citations = list(range(1, len(records) + 1))

    return {
        "answer": answer,
        "backend": backend,
        "model": model,
        "citations": citations,
    }


def backend_status():
    """Human-readable description of which generator is active."""
    if DEEPSEEK_API_KEY:
        return f"DeepSeek ({DEEPSEEK_MODEL})"
    if OLLAMA_BASE_URL:
        return f"Ollama ({OLLAMA_MODEL})"
    return "offline engine (no API key configured)"
