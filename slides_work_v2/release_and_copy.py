# -*- coding: utf-8 -*-
"""Release the locked target DOCX: back up any dirty open copy, close Word, copy staged build in."""
import shutil
import sys
import win32com.client

OPEN_PATH = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\P14_Learning_Summary.docx"
BACKUP = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\user-edit-before-affil.docx"
STAGED = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\P14_Learning_Summary.staged.docx"

try:
    word = win32com.client.GetActiveObject("Word.Application")
except Exception as exc:
    print("no active Word:", exc)
    word = None

doc = None
if word is not None:
    for d in word.Documents:
        if d.FullName.lower() == OPEN_PATH.lower():
            doc = d
            break

if doc is not None:
    print("open doc found, Saved =", doc.Saved)
    if not doc.Saved:
        doc.SaveAs2(BACKUP, FileFormat=16)
        print("dirty copy backed up:", BACKUP)
    doc.Close(0)
    print("closed")
else:
    print("target not open in Word")

shutil.copyfile(STAGED, OPEN_PATH)
print("staged copied to target")
