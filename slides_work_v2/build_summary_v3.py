# -*- coding: utf-8 -*-
"""Build the final P14_Learning_Summary.docx on top of the course template.

Template: Template_Learning_Summary.docx (IEEE-style, US Letter, Times New Roman, max 4 pages).
Filled: project ID P14, three member names, affiliations, YouTube demo link, GitHub link.
Still pending user input: contact email.

Body is reflection-only: what we learned, learning progress, overall impression
and enjoyment. The finished system is not described in the body.
"""
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

SRC = r"C:\Users\johnn\Downloads\Template_Learning_Summary.docx"
OUT = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\P14_Learning_Summary.staged.docx"

TNR = "Times New Roman"
BLACK = "000000"

AFFIL_1 = "Hong Kong Baptist University Affiliated School Wong Kam Fai Secondary and Primary School, Hong Kong, China"
AFFIL_2 = "HKSYC&IA Wong Tai Shan Memorial College, Hong Kong, China"
AFFIL_3 = "Baptist Lui Ming Choi Secondary School, Hong Kong, China"
YOUTUBE = "https://youtu.be/nVgevH43FYA"
GITHUB = "https://github.com/wts220828/Gef26-project-blockchain"

REFS = [
    "NIST, FIPS 202: SHA-3 Standard: Permutation-Based Hash and Extendable-Output Functions, Aug. 2015.",
    "RSA Laboratories / IETF, RFC 8017: PKCS #1: RSA Cryptography Specifications Version 2.2 (RSA-PSS), 2017.",
    "Standards for Efficient Cryptography (SEC 1) / ANSI X9.62: Elliptic Curve Cryptography (ECDSA, secp256r1).",
    "N. Reimers and I. Gurevych, \u201cSentence-BERT: Sentence Embeddings using Siamese BERT-Networks,\u201d EMNLP-IJCNLP, 2019.",
    "J. Johnson, M. Douze, and H. J\u00e9gou, \u201cBillion-Scale Similarity Search with GPUs (FAISS),\u201d IEEE Trans. Big Data, 2017.",
    "S. Ram\u00edrez, FastAPI documentation. [Online]. Available: https://fastapi.tiangolo.com",
    "PyCA, cryptography: Python cryptographic library. [Online]. Available: https://cryptography.io",
    "reportlab: PDF generation toolkit, https://www.reportlab.com; pypdf, https://pypdf.readthedocs.io",
    "Wikipedia REST API; DuckDuckGo Instant Answer API (public web lookup backends).",
    "Ollama: local LLM runtime. [Online]. Available: https://ollama.com",
]

doc = Document(SRC)
body = doc.element.body

children = list(body)


def p_text(el):
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def has_sectpr(el):
    ppr = el.find(qn("w:pPr"))
    return ppr is not None and ppr.find(qn("w:sectPr")) is not None


paras = [el for el in children if el.tag == qn("w:p")]

title_p = next(p for p in paras if p_text(p).startswith("How to write"))
authors_p = next(p for p in paras if p_text(p).startswith("First A. Author"))
aff_ps = [p for p in paras if p_text(p).strip().startswith(("1Kowloon", "2 Hong Kong", "3 Hong Kong"))]
contact_p = next(p for p in paras if p_text(p).startswith("*Contact"))
sect_paras = [p for p in paras if has_sectpr(p)]
break1_p = sect_paras[0]
break2_p = sect_paras[1]
abstract_p = next(p for p in paras if p_text(p).startswith("Abstract"))

retained = {title_p, authors_p, *aff_ps, contact_p, break1_p, abstract_p, break2_p}
for el in list(body):
    if el.tag == qn("w:sectPr"):
        continue
    if el in retained:
        continue
    if el.tag in (qn("w:p"), qn("w:tbl")):
        body.remove(el)


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
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        jc = ppr.makeelement(qn("w:jc"), {})
        ppr.append(jc)
    jc.set(qn("w:val"), align)
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        ind = ppr.makeelement(qn("w:ind"), {})
        ppr.append(ind)
    if first_line is not None:
        ind.set(qn("w:firstLine"), str(first_line))
    if hanging is not None:
        ind.set(qn("w:hanging"), str(hanging))
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


clear_runs(break1_p)
clear_runs(break2_p)

fill_slot(title_p, [("Mobile Credential Verification Portal", False, False, False, False)], 24)

fill_slot(authors_p, [
    ("Yau Ka Chai Johnny", False, False, False, False), (" (1)", False, False, False, False),
    (", Yu Siu Kui", False, False, False, False), (" (2)", False, False, False, False),
    (", and Yu Yeuk Lan Serena", False, False, False, False), (" (3)", False, False, False, False),
], 11)

aff_texts = [
    "(1) " + AFFIL_1,
    "(2) " + AFFIL_2,
    "(3) " + AFFIL_3,
]
for p_el, txt in zip(aff_ps, aff_texts):
    fill_slot(p_el, [(txt, False, True, False, False)], 9)

fill_slot(contact_p, [
    ("*Contact: ", False, False, False, False),
    ("[team contact e-mail]", False, False, False, False),
], 9, font="Courier New")


def add_body(segments, align="both", first_line=216, hanging=None, before=0, after=40, pt=10, heading=False, line=400):
    p = doc.add_paragraph()
    break2_p.addprevious(p._element)
    if heading:
        set_pPr(p._element, align="left", first_line=0, hanging=None, before=150, after=60, line=240)
    else:
        set_pPr(p._element, align=align, first_line=first_line, hanging=hanging, before=before, after=after, line=line)
    for text, bold, italic, sc in segments:
        r = p.add_run(text)
        style_run(r, pt, bold=bold, italic=italic, small_caps=sc)
    return p


def heading(num, text):
    label = f"{num}.  {text}" if num else text
    add_body([(label, True, False, True)], heading=True)


def body_p(text):
    add_body([(text, False, False, False)], line=400)


def ref_p(num, text):
    add_body([(f"[{num}] ", False, False, False), (text, False, False, False)],
             align="both", first_line=0, hanging=216, pt=8, line=240)


abstract = ("This summary reflects on our experience in the P14 course: what we learned, how our "
"understanding developed over the term, our overall impression of the course, and whether we enjoyed "
"the work. It is written from a learning perspective rather than as a description of the finished "
"system. The notes below cover the security and AI concepts we encountered, how our study progressed "
"in stages, what frustrated us, what we found rewarding, and where we want to go next.")
fill_slot(abstract_p, [
    ("Abstract", True, True, False, False),
    ("— " + abstract, False, False, False, False),
], 9, align="both", first_line=0)

# I. Course Context
heading("I", "Course Context")
body_p("The programme covered two connected pillars: cybersecurity and generative AI. The cybersecurity "
"strand moved from common threats and how systems are protected, through cryptography, hash functions "
"and digital signatures, to cloud and network security and ethical considerations. The AI strand "
"introduced machine learning and neural-network basics, large language models, word embedding and the "
"transformer architecture, together with AI ethics and explainability. Most sessions were lectures that "
"introduced these ideas.")
body_p("Most of our learning came from those lecture sessions and the material they covered. Gaps usually "
"surfaced when we checked our own understanding against what was explained in the lectures. "
"This summary looks back at that process: what clicked, what took longer than expected, and how our "
"attitudes toward the subject changed over the term.")
body_p("Before the course, our idea of whether a document was reliable was mostly that it came from a "
"credible source; we had not thought much about how that reliability could be checked independently, or "
"about what safeguards protect information once it leaves its original context. The course "
"pushed us to ask a different question: how can a later check confirm that something is genuine, rather "
"than relying on reputation or memory? That shift in question was one of the most important things we "
"took away, and it shaped how we read the rest of the material.")

# II. What We Learned
heading("II", "What We Learned")
body_p("On the security side, one of the first ideas was message integrity. A hash function turns data "
"into a fixed-length digest, and even a small change to the data produces a completely different digest. "
"Comparing the digest lets a later check tell whether the data has been altered, which is the basic idea "
"behind detecting tampering. We learned that integrity is not the same as secrecy: encryption keeps "
"content private, while hashing shows whether content has stayed the same.")
body_p("We studied how digital signatures bind a signer to a message. A signature is created with the "
"signer\u2019s private key and can be verified with the matching public key, so a recipient can confirm "
"both who produced the message and that it has not been changed since. We also saw why the trustworthiness "
"of the key itself matters: a signature can only be relied on if the public key belongs to the party it "
"claims to represent. Access control decides who may read or act on information, which complements these "
"cryptographic checks.")
body_p("The course also covered the wider security picture. Symmetric and asymmetric encryption solve "
"different parts of the same problem of keeping communications private, and key exchange is how two "
"sides establish a shared secret without meeting in person. Secure communication protocols add another "
"layer when data moves across a network. On the threat side, we looked at how phishing, malware and "
"ransomware spread and the basic practices that reduce these risks, along with cyber ethics and the legal "
"responsibilities that come with working with systems and personal data.")
body_p("On the AI side, the foundational lectures introduced machine learning, neural networks and how a "
"model learns from data and then makes an inference, before moving on to large language models, "
"tokenisation, word embedding and the attention and transformer ideas behind text generation. One lesson "
"that stood out was what a reliable answer depends on. A model can produce fluent sentences that sound "
"convincing, but an answer about a specific subject has to be tied to the actual source material rather "
"than to what the model happens to expect. Answers should be grounded in the material that was retrieved "
"and should show where each claim comes from, so a reader can check it instead of taking the model\u2019s "
"word for it.")
body_p("Privacy and responsible use were central lessons. Sensitive details should not appear in what an "
"AI system surfaces, and the way a person\u2019s context is described has to be limited to what the "
"question actually needs. We also learned the value of a safe fallback: when an AI backend is unavailable, "
"the system should say only what it can support from known facts and should not invent details to fill "
"the gap. Explainability matters for the same reason: an answer should be understandable and traceable, "
"not just confident. Seeing these constraints laid out made the difference between a helpful system "
"and an overconfident one feel much clearer than it had in the abstract.")
body_p("The course also touched on the engineering ideas that secure and reliable systems rely on: keeping "
"optional parts behind a clear interface so the rest can keep working when one component changes, "
"checking behaviour with tests, keeping components isolated so a problem in one place does not affect "
"another, and designing a safe fallback when an external service is unavailable. These are ideas we "
"understood at a conceptual level; they help explain why a system is built the way it is, rather than a "
"practice we carried out in depth.")

# III. Learning Progress
heading("III", "Learning Progress")
body_p("Our understanding developed gradually rather than all at once. At the beginning, the terms "
"around hashing, signatures and retrieval were mostly definitions we could repeat back. We could "
"describe what a concept was supposed to do, but we had not yet seen where it would matter or how it "
"would fail in practice. The first reading and first small steps felt unfamiliar, and many of the "
"ideas only became concrete once we had to explain them and check them against the course material.")
body_p("As the term went on, the separate pieces started to connect. We stopped treating hashing, "
"signing, retrieval and privacy as unrelated topics and began to see how one step constrains the next: "
"information has to be stored in a way that can be checked, protected so it cannot be changed quietly, "
"searched without giving away private details, and explained so a non-expert can follow it. Each small "
"round of checking what we understood against the course examples revealed gaps that reading alone had "
"hidden, and fixing those gaps taught us more than the initial explanation had.")
body_p("By the later stages, moving from lecture material to a concrete problem felt noticeably less "
"intimidating. We could judge why one choice was safer than another, point to the weak points in an "
"approach, and ask the right questions about how it was put together. Our confidence was not "
"the same as knowing everything; we still relied on references and on checking our assumptions, but we "
"had moved from following material passively to reasoning about it ourselves.")
body_p("Repeated review helped the ideas settle. Going back over the material, explaining a concept in our "
"own words, and checking it against what the lectures covered exposed assumptions we had not noticed and "
"kept our understanding consistent with the course. The parts that felt unclear at first usually became "
"clearer after a second or third pass.")

# IV. Overall Impression and Enjoyment
heading("IV", "Overall Impression and Enjoyment")
body_p("Our overall impression is that the course topics fit together more closely than they first "
"appear. Information has to be recorded, protected, retrieved, explained and kept private, and a decision "
"in one area affects all the others. Seeing these connections emerge across the term gave the course a "
"coherence that isolated textbook chapters do not always have. We left with a clearer sense of where "
"cryptography, AI retrieval and privacy meet, and of the kinds of questions that come up when these "
"areas are applied to a real problem.")
body_p("We enjoyed the parts where an idea finally made sense. Even though most of the course was "
"lectures, seeing how a concept from class fit together felt rewarding, and being able to explain it in "
"our own words was satisfying. The satisfaction came from understanding why something worked.")
body_p("The difficult parts were the abstract trade-offs that sit between security, privacy and "
"usefulness: information has to be protected, but it also has to be understandable and usable, and "
"choices that help one goal can weaken another. Some ideas took longer to settle because a short "
"explanation hides how the steps connect, and the gaps between the lectures and the whole picture only "
"became visible after review. Working through these points felt more useful than following a prepared "
"tutorial, and it taught us how to keep going when the obvious answer did not explain everything.")
body_p("The experience left us interested in learning more. Several of us would like to go deeper into "
"applied cryptography and how signature and hash schemes are chosen for real systems, and others were "
"drawn to retrieval systems, how answers are kept grounded, and how privacy can be designed into an AI "
"system rather than added afterward. We would like to spend more time on these topics in a more "
"practical setting later.")
body_p("If we had to give one piece of advice to students taking the course later, it would be to spend "
"time on the basics before trying to connect everything: hashing, signatures, retrieval and privacy "
"each look simple in a short explanation, but they only become clear once you can trace what each step "
"actually protects or reveals. The course rewards the parts that feel slow at first, because those are "
"the parts that hold the whole idea together. We left feeling that we had only scratched the surface, "
"but that the surface was enough to show where the deeper questions lie.")

# Resources (required submission links)
heading("", "Resources")
body_p("Demonstration video (YouTube): " + YOUTUBE + ".")
body_p("Source code repository (GitHub): " + GITHUB + ".")

# References (8 pt, hanging indent, [n])
heading("", "References")
for _i, _ref in enumerate(REFS, 1):
    ref_p(_i, _ref)

doc.save(OUT)
print("SAVED", OUT)
print("paragraphs:", len(doc.paragraphs))
