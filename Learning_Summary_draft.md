# Learning Summary — [PROJECT ID]

> Draft for the CityUHK EE GenAIC submission. Fill every bracketed placeholder.
> The final version must be pasted into the course `Template_Learning_Summary.docx`
> and saved as `[PROJECT ID]_Learning_Summary.docx`.

- **Project title:** QuantumGuard / GEF Mobile — A Post-Quantum Credential Verification Portal
- **Project ID:** [PROJECT ID, e.g. P01]
- **Team members:** [Name 1], [Name 2], [Name 3]
- **Demo video (YouTube):** [LINK PROVIDED BY TEAMMATE]
- **Source code (GitHub):** https://github.com/JohnnyYau/gef-mobile-credential-portal

---

## 1. Problem Statement

Academic credentials — degrees, transcripts, certificates — are verified for
decades after issuance, yet most institutions still rely on centralized registrar
databases and classical digital signatures. This creates two problems.

1. **Slow, costly and fragile verification.** Employers and registrars must call
   or email the issuing office, wait days, and trust a database that can be edited,
   backed up inconsistently, or lost when an institution closes.
2. **Long-term cryptographic risk.** RSA and ECDSA rely on integer factorization
   and discrete logarithms, both of which a sufficiently large quantum computer
   can break with Shor's algorithm. Credentials live for 30–50 years, so a
   "harvest now, decrypt/forge later" window is a realistic threat.

There is no lightweight, explainable tool that lets a non-expert verifier confirm a
credential's authenticity in seconds, with a tamper-evident record and a clear
audit trail.

## 2. Proposed Solution

We built a private hash-chain credential portal that issues, revokes and verifies
academic credentials with **post-quantum digital signatures**, and wraps the
chain in a browser-friendly portal for three personas: **verifiers/employers**,
**students** and **registrars/administrators**.

The chain stores **only credential hashes and signatures**; plaintext credential
data never touches the ledger. A verifier uploads a credential JSON or a
portal-issued diploma PDF, and the portal runs six independent cryptographic
checks and returns a plain-language verdict: **VALID**, **REVOKED**, **NOT FOUND**
or **INVALID**, with a downloadable verification receipt.

Key capabilities shipped:

- Six-check on-chain verification with verdict receipts and a receipt registry.
- Verifiable diploma PDFs that embed the exact credential JSON; QR codes linking to
  the public verification URL.
- Registrar batch issuance from CSV (preview → issue → per-row PDF/QR), bulk
  revocation with reason and effective date.
- Employer pack: batch verify CSV-in/CSV-out, public API keys with per-key rate
  limits, signed revocation status list (OCSP-like, cacheable).
- An AI assistant over the chain: retrieval-augmented answers with cited sources,
  masked person-in-context profiles, follow-up memory, and privacy-preserving web
  research.
- Public verifier mode: the deployed URL verifies but cannot issue or revoke.
- Self-service credential maker: fill a form, build a JSON/PDF and optionally issue
  it onto the chain; data syncs to the project workspace.
- Persistent anonymized public log, IsolationForest anomaly watch, restart
  persistence (chain snapshot backup/restore), and hardened inputs and rate limits.

## 3. System Architecture

```
Registrar / Student
        │  JSON or portal-issued PDF
        ▼
FastAPI portal (app/main.py, static/index.html)
   ├── chain_service.py    issue / revoke / verify, signer registry, student lookup
   ├── crypto_util.py      ML-DSA-65 / RSA-PSS-2048 / ECDSA secp256r1, SHA3-512
   ├── blockchain_util.py  append-only hash chain, block integrity re-verification
   ├── chat_service.py     RAG orchestration: exact lookup → retrieve → generate → sources
   ├── rag_indexer / embedder / generator  MiniLM-L6-v2 + FAISS; DeepSeek/Ollama/offline
   ├── person_context.py   masked profile cards + session anaphora
   ├── web_research.py     Wikipedia / DuckDuckGo public lookups (privacy-preserving query)
   ├── pdf_diploma.py / pdf_extractor.py   render diploma PDF; extract embedded/text JSON
   └── employer pack        API keys, signed status list, receipt registry, batch verify
        │  hashes + signatures only
        ▼
Private append-only chain (JSON blocks, previous_hash links)
        │  plaintext kept off-chain (rawjsondocs index, issuer-side)
        ▼
Public log / receipts / anomaly watch
```

**Design choices.** A single-node private chain focuses the project on
cryptographic and verification principles rather than distributed consensus. The
chain is append-only and fully replayable: integrity is re-verified from the
genesis block on every verification.

## 4. Technology Stack

| Layer | Choice | Role |
|---|---|---|
| Language / web | Python 3, FastAPI, Uvicorn, python-multipart | REST API + static single-page UI (plain HTML/JS fetch, no framework) |
| Cryptography | PyCA `cryptography`; ML-DSA-65 (post-quantum), RSA-PSS-2048, ECDSA secp256r1 | Issuer signing and signature verification; multi-signer registry |
| Hashing | SHA3-512 over JCS-canonicalized JSON (`jcs`) | Credential part-hashes and chain block linking |
| PDF | reportlab, pypdf | Diploma rendering; embedded credential JSON; byte-exact extraction |
| Embeddings / search | sentence-transformers `all-MiniLM-L6-v2`, FAISS IndexFlatIP (numpy fallback) | RAG retrieval over chain blocks and raw credentials |
| LLM backends | DeepSeek API / Ollama local model / deterministic offline engine | Answer generation; offline fallback cannot invent chain facts |
| Anomaly detection | scikit-learn IsolationForest (contamination 0.15) + deterministic rule | Per-signer hourly issuance anomaly watch |
| Other | qrcode, PyYAML, httpx (tests), IsolationForest | QR codes, chain config, test client |
| Deployment | Dockerfile, Render `render.yaml`, Railway `railway.toml`, `/healthz` | Free-tier deployment with restart-persistence snapshot |

## 5. How Verification Works (the six checks)

All six must pass for **VALID**:

1. **Chain integrity** — the whole chain re-verifies from genesis (hashes, links,
   heights).
2. **Signer trusted** — every ISSUE-block signer is in the registry (SPKI
   fingerprint match).
3. **On-chain record** — an ISSUE block exists whose `HashedDocument` matches the
   presented document.
4. **Hash match** — recomputed part-hashes of the presented document equal the
   on-chain payload.
5. **Signature valid** — each signer's DS signature verifies over the nonce-HMAC
   message.
6. **Not revoked** — no REVOKE block references this document hash (reason and
   effective date recorded on-chain when present).

A hash-only lookup cannot run check 4 (it needs the full document), so it returns
`VALID ON CHAIN` / `REVOKED` / `NOT FOUND` / `INVALID` / `CHAIN DATA CORRUPT`.
Every verdict produces a receipt ID; the receipt shows the six checks, hash,
timestamp, verifier version, chain name and height, and an explicit disclaimer:
*"VALID means the six checks passed against the chain at this timestamp; it is
not a legal certification."* No DOB and no Student ID appear in the receipt.

## 6. AI / Generative-AI Components

Because this is a GenAI course, the AI layer is built as a privacy-controlled
assistant over the credential chain:

- **RAG chat.** Questions first hit exact identifier lookup (hash / StudentID /
  name, pinned before vector search), then MiniLM-L6-v2 embeddings are searched
  with FAISS over chain blocks and raw credentials. The generator answers with
  cited sources; the offline deterministic engine only reads chain state and
  cannot hallucinate.
- **Person in context.** A named person (or StudentID) resolves to a masked
  profile card: name, truncated StudentID, document type, degree, dates, honour,
  issuer, verdict, height and hash prefix. DOB is never included. Session memory
  keeps the same person across follow-ups ("what degree does he hold?").
- **Web research.** When asked to search the web, the assistant queries only the
  person's name + issuing organisation (no StudentID, no DOB) against Wikipedia
  and DuckDuckGo Instant Answer. Results come back as a clearly labelled
  "public web" card and never change the on-chain verdict.
- **Anomaly watch.** IsolationForest flags unusual per-signer issuance volume and
  merges the result with a deterministic threshold rule; the method used is
  reported per flag.
- **PDF auto-fill.** Uploading a certificate PDF fills the credential JSON form:
  portal-issued PDFs are extracted byte-exact from the embedded payload
  (`embedded_payload`, confidence 1.0); text-layer certificates get label-aware
  English/Chinese field extraction with per-field confidence. Extraction is input
  assistance only — it never bypasses the six checks and never auto-submits.

## 7. Relevance to Course Materials

- **P3L3 (Blockchain):** hash chaining, blocks, transactions and ledger
  append-only/immutability principles; replayable chain integrity verification.
- **P2L3 (Public Key Cryptography):** digital signatures, key pairs, trust
  registry and trapdoor-function assumptions behind classical vs post-quantum
  schemes.
- **P2L4 (Hash Functions):** SHA3-512 integrity hashing, canonicalization before
  hashing, and block `previous_hash` linking.
- **P2L5 (Digital Signatures):** signature generation/verification logic,
  signer rotation and revocation semantics.
- **GenAI / RAG:** embedding models, vector retrieval, LLM generation with
  fallbacks, citation grounding, and privacy-preserving AI assistants.

## 8. Demo Walkthrough

The teammate's YouTube recording shows the real portal:

1. Role-based landing page (verifier / student / registrar).
2. VALID sample → six checks pass in seconds → **真实有效 VALID**, receipt download.
3. Upload a portal-issued diploma PDF → byte-exact extraction → full six-check
   VALID verdict with holder summary.
4. Self-service maker: fill the form → issue onto the chain → download PDF/JSON →
   verify back as genuine.
5. Public anonymized log with chain tail and anomaly watch.

Local artifacts: `demo-media/GEF-mobile-demo.mp4` (67.5 s, English narration),
`demo-media/poster-海报-v2.png` (project poster).

## 9. Implementation Status & Testing

- 108 automated test cases across 12 modules: API, hardening, RAG, features,
  employer pack, public mode, restart persistence, batch issue, PDF extraction,
  person-in-context, self-service maker.
- Verified flows: issue → verify VALID; tampered document → INVALID; revoked
  credential → REVOKED; PDF upload auto-fill → verify; restart persistence with
  snapshot export/restore.
- Hardening: sliding-window rate limiting, body-size and nesting guards,
  corrupt-chain structured verdicts, atomic chain-info writes.

## 10. Limitations & Honest Boundaries

- Single-node private chain: no P2P consensus or peer replication by design; the
  focus is cryptographic verification, not distributed systems engineering.
- Demo signer private keys live under `data/demo-chain/keys/` for demonstration
  only; production would use a KMS/HSM.
- PDF verification supports portal-issued PDFs (embedded JSON); a printed or
  scanned external diploma cannot be OCR'd into the exact hashed fields, and
  gets a clear guidance message instead of a guessed verdict.
- The plaintext index (`rawjsondocs/`) is issuer-side; a production deployment
  would back it with a database without touching the chain.
- Web research requires outbound internet; offline, the assistant reports it is
  unavailable rather than inventing sources.
- A VALID verdict is a cryptographic statement at a timestamp, not a legal
  certification of the credential's underlying qualification.

## 11. Individual Reflection

> Replace with each member's own summary once the team agrees on the split.

- **[Name 1]** — [what you worked on: e.g., chain design, signatures, six-check
  verification; what you learned about blockchain and PQC].
- **[Name 2]** — [what you worked on: e.g., RAG assistant, embeddings, person
  context; what you learned about retrieval-augmented generation and privacy].
- **[Name 3]** — [what you worked on: e.g., portal UI, PDF/QR, deployment,
  testing; what you learned about UX for non-experts and production hardening].

## 12. References

1. NIST. *FIPS 204: Module-Lattice-Based Digital Signature Standard (ML-DSA)*.
   August 2024.
2. NIST. *FIPS 202: SHA-3 Standard: Permutation-Based Hash and Extendable-Output
   Functions*. August 2015.
3. RSA Laboratories / IETF. *RFC 8017: PKCS #1: RSA Cryptography Specifications
   Version 2.2 (RSA-PSS)*. 2017.
4. Standards for Efficient Cryptography (SEC 1) / ANSI X9.62: Elliptic Curve
   Cryptography (ECDSA, secp256r1).
5. IETF. *RFC 8785: JSON Canonicalization Scheme (JCS)*. 2020.
6. Reimers, N., & Gurevych, I. (2019). *Sentence-BERT: Sentence Embeddings using
   Siamese BERT-Networks*. EMNLP-IJCNLP.
7. Johnson, J., Douze, M., & Jégou, H. (2017). *Billion-Scale Similarity Search
   with GPUs (FAISS)*. IEEE Transactions on Big Data.
8. Liu, F. T., Ting, K. M., & Zhou, Z.-H. (2008). *Isolation Forest*. IEEE ICDM.
9. Ramírez, S. *FastAPI documentation*. https://fastapi.tiangolo.com.
10. PyCA. *cryptography: Python cryptographic library*. https://cryptography.io.
11. reportlab: PDF generation toolkit, https://www.reportlab.com; pypdf,
    https://pypdf.readthedocs.io.
12. W3C. *Verifiable Credentials Data Model v2.0* (conceptual reference).
13. Wikipedia REST API; DuckDuckGo Instant Answer API (public web lookup
    backends).
14. DeepSeek API documentation; Ollama: local LLM runtime (optional generator
    backends).
