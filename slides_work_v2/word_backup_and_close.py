# -*- coding: utf-8 -*-
"""Back up the user's open (dirty) Word copy, then close it so the corrected build can be written."""
import shutil
import win32com.client

OPEN_PATH = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\P14_Learning_Summary.docx"
BACKUP = r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\user-edit-before-fix.docx"

word = win32com.client.GetActiveObject("Word.Application")
doc = None
for d in word.Documents:
    if d.FullName.lower() == OPEN_PATH.lower():
        doc = d
if doc is None:
    raise SystemExit("target not open")

print("saving user copy to backup:", BACKUP)
doc.SaveAs2(BACKUP, FileFormat=16)  # wdFormatDocumentDefault (.docx)
print("backup saved, Saved flag now:", doc.Saved)
doc.Close(0)
print("closed without further save")

shutil.copyfile(BACKUP, r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\slides_work_v2\user-edit-check.docx")
print("done")
