# -*- coding: utf-8 -*-
"""Verify the generated P14 summary: placeholders, key facts, headings, length."""
from docx import Document

PATH = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\P14_Learning_Summary.docx"
doc = Document(PATH)

texts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
full = "\n".join(texts)

print("paragraphs:", len(texts))
print("chars:", len(full))
words = len(full.split())
print("words:", words)

bad_patterns = ["[Name", "First A. Author", "How to write", "Kowloon", "1Kowloon",
                "email@example.com", "LINK PROVIDED", "LINK AFTER GITHUB", "et al."]
for pat in bad_patterns:
    print(f"residual {pat!r}: {full.count(pat)}")

checks = {
    "P14": "P14",
    "youtube": "https://youtu.be/nVgevH43FYA",
    "309 tests": "309 automated tests",
    "27 modules": "27 isolated modules",
    "names Johnny": "Yau Ka Chai Johnny",
    "names Siu Kui": "Yu Siu Kui",
    "names Serena": "Yu Yeuk Lan Serena",
    "affil": "City University of Hong Kong",
    "fips204": "FIPS 204",
    "ref14": "[14]",
}
for label, needle in checks.items():
    print(f"{label}: {needle in full}")

print("--- headings / first lines ---")
for t in texts[:8]:
    print("|", t[:110])

print("--- tables:", len(doc.tables), " images(inline):", len(doc.inline_shapes) if hasattr(doc, "inline_shapes") else "n/a")

# page size sanity (US Letter = 12240 x 15840 twips)
sec = doc.sections[0]
print("page w/h:", sec.page_width, sec.page_height)
