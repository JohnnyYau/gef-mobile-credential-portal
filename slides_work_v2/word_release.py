# -*- coding: utf-8 -*-
"""Attach to the running Word instance, report dirty state, and close the target doc only if clean."""
import sys

TARGET = r"c:\users\johnn\doubao\chats\2026-10-22\new-chat\gef-mobile-project\p14_learning_summary.docx"

try:
    import win32com.client
except ImportError:
    print("NO_PYWIN32")
    sys.exit(2)

word = win32com.client.GetActiveObject("Word.Application")
print("attached, documents:", word.Documents.Count)

target = None
for d in word.Documents:
    path = (d.FullName or "").lower()
    print("DOC:", d.FullName, "| Saved:", d.Saved, "| ReadOnly:", d.ReadOnly, "| Revisions:", d.Revisions.Count)
    if path == TARGET:
        target = d

if target is None:
    print("TARGET_NOT_OPEN")
    sys.exit(3)

if not target.Saved:
    print("HAS_UNSAVED_EDITS - not closing")
    sys.exit(4)

target.Close(0)  # wdDoNotSaveChanges
print("CLOSED_CLEAN")
