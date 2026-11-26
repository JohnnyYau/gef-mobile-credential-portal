# -*- coding: utf-8 -*-
"""Dump the exact author/affiliation strings stored in the generated DOCX."""
from docx import Document

PATH = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\P14_Learning_Summary.docx"
doc = Document(PATH)
for i, p in enumerate(doc.paragraphs[:6]):
    print(i, repr(p.text))
