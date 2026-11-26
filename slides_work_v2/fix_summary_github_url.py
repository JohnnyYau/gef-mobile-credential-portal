"""Replace the stale GitHub URL inside P14_Learning_Summary.docx.

Rewrites word/document.xml in place (same run, same formatting), keeping every
other zip entry byte-identical.
"""

import shutil
import sys
import zipfile
from pathlib import Path

DOCX = Path(sys.argv[1])
OLD = "https://github.com/wts220828/Gef26-project-blockchain"
NEW = "https://github.com/JohnnyYau/gef-mobile-credential-portal"

backup = DOCX.with_suffix(".docx.bak")
if not backup.exists():
    shutil.copy2(DOCX, backup)

src = zipfile.ZipFile(backup)
items = [(i, src.read(i.filename)) for i in src.infolist()]
src.close()

changed = 0
tmp = DOCX.with_suffix(".docx.tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
    for info, data in items:
        if info.filename == "word/document.xml":
            text = data.decode("utf-8")
            if OLD in text:
                text = text.replace(OLD, NEW)
                changed += 1
            data = text.encode("utf-8")
        out.writestr(info, data)

if changed:
    tmp.replace(DOCX)
    print(f"replaced -> {NEW}")
else:
    tmp.unlink()
print(f"backup: {backup.name}")
