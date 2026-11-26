import zipfile, re
for tag, p in [("SRC", r"C:\Users\johnn\Downloads\Template_Learning_Summary.docx"), ("OUT", r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\Learning_Summary_draft.docx")]:
    z = zipfile.ZipFile(p)
    print("====", tag)
    for n in z.namelist():
        print(" ", n)
    xml = z.read("word/document.xml").decode("utf-8")
    print("  body count:", xml.count("<w:body>"), "altChunk:", xml.count("altChunk"), "sectPr:", xml.count("<w:sectPr"))