# -*- coding: utf-8 -*-
"""Fill the course IEEE-style Learning Summary template with QuantumGuard content.

Reuses the template's page setup, section breaks, headers/footers and fonts;
replaces instruction text, sample table and sample figures with our summary.
Unknown identities/links stay as explicit bracketed placeholders.
"""
import copy
from docx import Document
from docx.shared import Pt, Twips
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

SRC = r"C:\Users\johnn\Downloads\Template_Learning_Summary.docx"
OUT = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\Learning_Summary_draft.docx"

TNR = "Times New Roman"
BLACK = "000000"

doc = Document(SRC)
body = doc.element.body

# ---------- locate retained children ----------
children = list(body)
def p_text(el):
    return "".join(t.text or "" for t in el.iter(qn("w:t")))
def has_sectpr(el):
    ppr = el.find(qn("w:pPr"))
    return ppr is not None and ppr.find(qn("w:sectPr")) is not None

paras = [el for el in children if el.tag == qn("w:p")]
tbls = [el for el in children if el.tag == qn("w:tbl")]

# Retained section-1 slots (by text match)
title_p = next(p for p in paras if p_text(p).startswith("How to write"))
authors_p = next(p for p in paras if p_text(p).startswith("First A. Author"))
aff_ps = [p for p in paras if p_text(p).strip().startswith(("1Kowloon", "2 Hong Kong", "3 Hong Kong"))]
contact_p = next(p for p in paras if p_text(p).startswith("*Contact"))
sect_paras = [p for p in paras if has_sectpr(p)]
break1_p = sect_paras[0]
break2_p = sect_paras[1]
abstract_p = next(p for p in paras if p_text(p).startswith("Abstract"))

# ---------- delete all instruction children first, before adding our content ----------
retained = {title_p, authors_p, *aff_ps, contact_p, break1_p, abstract_p, break2_p}
for el in list(body):
    if el.tag == qn("w:sectPr"):
        continue
    if el in retained:
        continue
    if el.tag in (qn("w:p"), qn("w:tbl")):
        body.remove(el)

# ---------- clear helper ----------
def clear_runs(p_el):
    for child in list(p_el):
        if child.tag in (qn("w:r"), qn("w:hyperlink"), qn("w:fldSimple")):
            p_el.remove(child)

def style_run(run, pt, bold=False, italic=False, small_caps=False, font=TNR, underline=False):
    run.font.name = font
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rf)
    rf.set(qn("w:ascii"), font)
    rf.set(qn("w:hAnsi"), font)
    rf.set(qn("w:cs"), font)
    rf.set(qn("w:eastAsia"), font)
    run.font.size = Pt(pt)
    run.font.bold = bold
    run.font.italic = italic
    run.font.underline = underline
    run.font.small_caps = small_caps
    run.font.color.rgb = None
    col = rpr.find(qn("w:color"))
    if col is None:
        col = rpr.makeelement(qn("w:color"), {})
        rpr.append(col)
    col.set(qn("w:val"), BLACK)

def set_pPr(p_el, align="both", first_line=None, hanging=None, before=None, after=None, line=240):
    ppr = p_el.find(qn("w:pPr"))
    if ppr is None:
        ppr = p_el.makeelement(qn("w:pPr"), {})
        p_el.insert(0, ppr)
    # alignment
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        jc = ppr.makeelement(qn("w:jc"), {})
        ppr.append(jc)
    jc.set(qn("w:val"), align)
    # indent
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        ind = ppr.makeelement(qn("w:ind"), {})
        ppr.append(ind)
    if first_line is not None:
        ind.set(qn("w:firstLine"), str(first_line))
    if hanging is not None:
        ind.set(qn("w:hanging"), str(hanging))
    # spacing
    sp = ppr.find(qn("w:spacing"))
    if sp is None:
        sp = ppr.makeelement(qn("w:spacing"), {})
        ppr.append(sp)
    if before is not None:
        sp.set(qn("w:before"), str(before))
    if after is not None:
        sp.set(qn("w:after"), str(after))
    sp.set(qn("w:line"), str(line))
    sp.set(qn("w:lineRule"), "auto")

def fill_slot(p_el, segments, pt, align="center", first_line=0, hanging=None, before=None, after=None, font=TNR):
    """segments: list of (text, bold, italic, small_caps, underline)."""
    clear_runs(p_el)
    set_pPr(p_el, align=align, first_line=first_line, hanging=hanging, before=before, after=after)
    para = Paragraph(p_el, doc)
    for text, bold, italic, sc, ul in segments:
        r = para.add_run(text)
        style_run(r, pt, bold=bold, italic=italic, small_caps=sc, underline=ul, font=font)

# ---------- section 1 header block ----------
clear_runs(break1_p)
clear_runs(break2_p)

fill_slot(title_p, [("QuantumGuard: A Post-Quantum Credential Verification Portal", False, False, False, False)], 24)

fill_slot(authors_p, [
    ("[Name 1]", False, False, False, False), (" (1)", False, False, False, False),
    (", [Name 2]", False, False, False, False), (" (2)", False, False, False, False),
    (", and [Name 3]", False, False, False, False), (" (3)", False, False, False, False),
], 11)

aff_texts = [
    "(1) [School / Institute, Hong Kong, China]",
    "(2) [School / Institute, Hong Kong, China]",
    "(3) [School / Institute, Hong Kong, China]",
]
for p_el, txt in zip(aff_ps, aff_texts):
    fill_slot(p_el, [(txt, False, True, False, False)], 9)

fill_slot(contact_p, [
    ("*Contact: ", False, False, False, False),
    ("[email@example.com]", False, False, False, False),
], 9, font="Courier New")

# ---------- abstract ----------
abstract = ("This project presents QuantumGuard, a browser-based portal that issues, revokes and "
"verifies academic credentials over a private append-only hash chain, combining post-quantum digital "
"signatures with a privacy-controlled GenAI assistant. The chain stores only credential hashes and "
"signatures; plaintext data stays off-chain. A verifier uploads a credential JSON or a portal-issued "
"diploma PDF, and the system runs six independent cryptographic checks and returns a plain-language "
"verdict (VALID, REVOKED, NOT FOUND or INVALID) with a downloadable receipt. The system ships a "
"three-role portal, registrar batch issuance, an employer pack (batch verification, public API keys, "
"signed status list, receipt registry), a RAG assistant with cited sources and masked person profiles, "
"anomaly detection, restart persistence and hardened inputs. The project maps directly to course topics "
"in blockchain, public-key cryptography, hash functions, digital signatures and retrieval-augmented "
"generation.")
fill_slot(abstract_p, [
    ("Abstract", True, True, False, False),
    ("— " + abstract, False, False, False, False),
], 9, align="both", first_line=0)

# ---------- new body content ----------
def add_body(segments, align="both", first_line=216, hanging=None, before=0, after=0, pt=10, heading=False):
    p = doc.add_paragraph()
    break2_p.addprevious(p._element)
    if heading:
        set_pPr(p._element, align="left", first_line=0, hanging=None, before=150, after=60)
    else:
        set_pPr(p._element, align=align, first_line=first_line, hanging=hanging, before=before, after=after)
    for text, bold, italic, sc in segments:
        r = p.add_run(text)
        style_run(r, pt, bold=bold, italic=italic, small_caps=sc)
    return p

def heading(num, text):
    label = f"{num}.  {text}" if num else text
    add_body([(label, True, False, True)], heading=True)

def body_p(text):
    add_body([(text, False, False, False)])

def ref(idx, segments):
    add_body(segments, align="both", first_line=0, hanging=432, pt=8)

# I. Introduction
heading("I", "Introduction")
body_p("Academic credentials — degrees, transcripts and certificates — are verified for decades after "
"issuance, yet most institutions still rely on centralized registrar databases and classical digital "
"signatures. Verification is slow and costly: employers and registrars call or email the issuing office "
"and wait days, while a central database can be edited, backed up inconsistently, or lost when an "
"institution closes. There is also a long-term cryptographic risk: RSA and ECDSA rely on integer "
"factorization and discrete logarithms, both breakable by a sufficiently large quantum computer using "
"Shor's algorithm. Because credentials live for 30–50 years, a “harvest now, forge later” window is "
"realistic. This project addresses that gap with a lightweight, explainable portal that lets a "
"non-expert verifier confirm authenticity in seconds, leaving a tamper-evident record and a clear audit "
"trail.")

# II. Proposed Solution
heading("II", "Proposed Solution")
body_p("We built a private hash-chain credential portal that issues, revokes and verifies academic "
"credentials with post-quantum digital signatures, wrapped in a browser-friendly FastAPI portal for "
"three personas: verifiers/employers, students, and registrars/administrators. The chain stores only "
"credential hashes and signatures; plaintext credential data never touches the ledger. A verifier uploads "
"a credential JSON or a portal-issued diploma PDF; the portal runs six independent cryptographic checks "
"and returns a plain-language verdict — VALID, REVOKED, NOT FOUND or INVALID — with a downloadable "
"verification receipt. Shipped capabilities include six-check verification with receipts and a receipt "
"registry; verifiable diploma PDFs embedding the exact credential JSON with a QR code to the public "
"verification URL; registrar batch issuance from CSV (preview, issue, per-row PDF/QR) and bulk revocation "
"with reason and effective date; an employer pack (CSV-in/CSV-out batch verification, per-key public API "
"keys with rate limits, a signed OCSP-like revocation status list); an AI assistant over the chain with "
"cited sources, masked person profiles, follow-up memory and privacy-preserving web research; a public "
"verifier mode that cannot issue or revoke; a self-service credential maker; a persistent anonymized "
"public log; IsolationForest anomaly watch; restart persistence via snapshot backup/restore; and hardened "
"inputs and rate limits.")

# III. Architecture and Cryptography
heading("III", "System Architecture and Cryptography")
body_p("The portal is a Python 3 FastAPI application with a static single-page HTML/JS front end. Core "
"modules handle chain service (issue, revoke, verify, signer registry, student lookup), cryptography "
"(ML-DSA-65 post-quantum signatures, RSA-PSS-2048, ECDSA secp256r1), an append-only hash chain with full "
"replayable integrity re-verification, the RAG chat service, person-in-context masking, privacy-"
"preserving web research, diploma PDF rendering and extraction, and the employer pack. Credential "
"part-hashes and block links use SHA3-512 over JCS-canonicalized JSON. The ledger is a single-node "
"private chain; this focuses the project on cryptographic and verification principles rather than "
"distributed consensus. The chain is append-only and fully replayable: integrity is re-verified from the "
"genesis block on every verification. Plaintext credentials remain in an issuer-side index, off the "
"chain.")
body_p("Course mapping: P3L3 blockchain (hash chaining, append-only immutability, replayable integrity); "
"P2L3 public-key cryptography (signatures, key pairs, trust registry, classical versus post-quantum "
"assumptions); P2L4 hash functions (SHA3-512, canonicalization, previous-hash linking); P2L5 digital "
"signatures (generation and verification, rotation and revocation semantics); and GenAI/RAG (embeddings, "
"vector retrieval, grounded generation with citations).")

# IV. AI / GenAI
heading("IV", "AI and Generative-AI Components")
body_p("The AI layer is a privacy-controlled assistant over the credential chain. Questions first hit exact "
"identifier lookup (hash, StudentID, name), pinned before vector search; MiniLM-L6-v2 embeddings are "
"then searched with FAISS over chain blocks and raw credentials. The generator answers with cited "
"sources; an offline deterministic fallback engine reads only chain state and cannot invent chain "
"facts. A named person or StudentID resolves to a masked profile card (name, truncated StudentID, "
"document type, degree, dates, honour, issuer, verdict, height and hash prefix); date of birth is never "
"included, and session memory keeps the same person across follow-ups. Web research queries only the "
"person's name and issuing organisation against Wikipedia and DuckDuckGo; results return as a clearly "
"labelled public-web card and never change the on-chain verdict. An IsolationForest (contamination 0.15) "
"flags unusual per-signer issuance volume and merges with a deterministic threshold rule, reporting the "
"method per flag. PDF auto-fill extracts the embedded payload byte-exactly from portal-issued PDFs "
"(confidence 1.0) and uses label-aware field extraction with per-field confidence for text-layer "
"certificates; extraction is input assistance only — it never bypasses the six checks and never "
"auto-submits.")

# V. Six checks
heading("V", "Verification: The Six Checks")
body_p("All six must pass for VALID: (1) chain integrity — the whole chain re-verifies from genesis "
"(hashes, links, heights); (2) signer trusted — every ISSUE-block signer is in the registry by SPKI "
"fingerprint match; (3) on-chain record — an ISSUE block exists whose HashedDocument matches the "
"presented document; (4) hash match — recomputed part-hashes equal the on-chain payload; (5) signature "
"valid — each signer's DS signature verifies over the nonce-HMAC message; (6) not revoked — no REVOKE "
"block references this document hash, with reason and effective date recorded on-chain when present. A "
"hash-only lookup cannot run check 4 and returns VALID ON CHAIN, REVOKED, NOT FOUND, INVALID or CHAIN "
"DATA CORRUPT. Every verdict produces a receipt ID; the receipt shows the six checks, hash, timestamp, "
"verifier version, chain name and height, and the explicit disclaimer: VALID means the six checks "
"passed against the chain at this timestamp; it is not a legal certification. No date of birth and no "
"Student ID appear in the receipt.")

# VI. Testing
heading("VI", "Testing and Deployment Status")
body_p("The suite contains 108 automated test cases across 12 modules covering the API, hardening, RAG, "
"features, employer pack, public mode, restart persistence, batch issue, PDF extraction, "
"person-in-context and self-service maker. Verified flows include issue-to-VALID verification, tampered "
"document to INVALID, revoked credential to REVOKED, PDF upload auto-fill to verification, and restart "
"persistence with snapshot export/restore. Hardening includes sliding-window rate limiting, body-size and "
"nesting guards, structured verdicts for corrupted chains, and atomic chain-info writes. A public "
"verifier mode exposes verification only; issuance and revocation stay private.")

# VII. Limitations
heading("VII", "Limitations and Boundaries")
body_p("The chain is single-node by design, with no P2P consensus or peer replication; the focus is "
"cryptographic verification, not distributed-systems engineering. Demo signer private keys are kept "
"under the demo data directory for demonstration only; production would use a KMS or HSM. PDF "
"verification supports portal-issued PDFs carrying an embedded JSON; a printed or scanned external "
"diploma cannot be OCR'd into the exact hashed fields and receives a clear guidance message instead of "
"a guessed verdict. The plaintext index is issuer-side; production would back it with a database without "
"touching the chain. Web research requires outbound internet; offline, the assistant reports it is "
"unavailable rather than inventing sources. A VALID verdict is a cryptographic statement at a timestamp, "
"not a legal certification of the underlying qualification.")

# VIII. Contributions
heading("VIII", "Individual Contributions")
body_p("[Name 1] — [chain design, signatures and six-check verification; learning on blockchain principles "
"and post-quantum cryptography].")
body_p("[Name 2] — [RAG assistant, embeddings and person context; learning on retrieval-augmented generation "
"and privacy].")
body_p("[Name 3] — [portal UI, PDF/QR, deployment and testing; learning on UX for non-experts and "
"production hardening].")

# Resources
heading("", "Project Resources")
body_p("Demonstration video (YouTube): [LINK PROVIDED BY TEAMMATE].")
body_p("Source code repository (GitHub): [LINK AFTER GITHUB PUSH].")

# References heading (unnumbered, per template)
add_body([("References", True, False, True)], heading=True)

refs = [
    [("[1] ", False, False, False), ("NIST, FIPS 204: Module-Lattice-Based Digital Signature Standard (ML-DSA)", False, True, False), (", Aug. 2024.", False, False, False)],
    [("[2] ", False, False, False), ("NIST, FIPS 202: SHA-3 Standard: Permutation-Based Hash and Extendable-Output Functions", False, True, False), (", Aug. 2015.", False, False, False)],
    [("[3] ", False, False, False), ("RSA Laboratories / IETF, RFC 8017: PKCS #1: RSA Cryptography Specifications Version 2.2 (RSA-PSS)", False, True, False), (", 2017.", False, False, False)],
    [("[4] ", False, False, False), ("Standards for Efficient Cryptography (SEC 1) / ANSI X9.62: Elliptic Curve Cryptography (ECDSA, secp256r1)", False, True, False), (".", False, False, False)],
    [("[5] ", False, False, False), ("IETF, RFC 8785: JSON Canonicalization Scheme (JCS)", False, True, False), (", 2020.", False, False, False)],
    [("[6] ", False, False, False), ("N. Reimers and I. Gurevych, “Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks,”", False, False, False), (" EMNLP-IJCNLP, 2019.", False, True, False)],
    [("[7] ", False, False, False), ("J. Johnson, M. Douze, and H. Jégou, “Billion-Scale Similarity Search with GPUs (FAISS),”", False, False, False), (" IEEE Trans. Big Data, 2017.", False, True, False)],
    [("[8] ", False, False, False), ("F. T. Liu, K. M. Ting, and Z.-H. Zhou, “Isolation Forest,”", False, False, False), (" IEEE ICDM, 2008.", False, True, False)],
    [("[9] ", False, False, False), ("S. Ramírez, FastAPI documentation", False, True, False), (". [Online]. Available: https://fastapi.tiangolo.com", False, False, False)],
    [("[10] ", False, False, False), ("PyCA, cryptography: Python cryptographic library", False, True, False), (". [Online]. Available: https://cryptography.io", False, False, False)],
    [("[11] ", False, False, False), ("reportlab: PDF generation toolkit", False, True, False), (", https://www.reportlab.com; pypdf, https://pypdf.readthedocs.io", False, False, False)],
    [("[12] ", False, False, False), ("W3C, Verifiable Credentials Data Model v2.0", False, True, False), (" (conceptual reference).", False, False, False)],
    [("[13] ", False, False, False), ("Wikipedia REST API; DuckDuckGo Instant Answer API", False, True, False), (" (public web lookup backends).", False, False, False)],
    [("[14] ", False, False, False), ("DeepSeek API documentation; Ollama: local LLM runtime", False, True, False), (" (optional generator backends).", False, False, False)],
]
for segments in refs:
    ref(None, segments)

doc.save(OUT)
print("SAVED", OUT)
print("paragraphs:", len(doc.paragraphs))
