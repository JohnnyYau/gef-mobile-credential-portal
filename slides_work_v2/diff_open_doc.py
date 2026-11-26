# -*- coding: utf-8 -*-
"""Diff the Word-open document text against the on-disk copy (read-only, no close)."""
import win32com.client
from docx import Document

OPEN_PATH = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\P14_Learning_Summary.docx"

word = win32com.client.GetActiveObject("Word.Application")
doc = None
for d in word.Documents:
    if d.FullName.lower() == OPEN_PATH.lower():
        doc = d
if doc is None:
    raise SystemExit("not open")

live = doc.Content.Text.replace("\r", "\n")
on_disk = "\n".join(p.text for p in Document(OPEN_PATH).paragraphs)

live_lines = [l.strip() for l in live.split("\n") if l.strip()]
disk_lines = [l.strip() for l in on_disk.split("\n") if l.strip()]

print("live paragraphs:", len(live_lines), "disk paragraphs:", len(disk_lines))
only_live = [l for l in live_lines if l not in disk_lines]
only_disk = [l for l in disk_lines if l not in live_lines]
print("--- only in open doc (%d) ---" % len(only_live))
for l in only_live[:10]:
    print(repr(l[:200]))
print("--- only on disk (%d) ---" % len(only_disk))
for l in only_disk[:10]:
    print(repr(l[:200]))
print("first live line:", repr(live_lines[0][:120]))
print("Saved flag:", doc.Saved)
