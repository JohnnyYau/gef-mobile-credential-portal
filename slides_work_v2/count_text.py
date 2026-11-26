import zipfile
for tag,p in [("SRC",r"C:\Users\johnn\Downloads\Template_Learning_Summary.docx"),("OUT",r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\Learning_Summary_draft.docx")]:
    xml=zipfile.ZipFile(p).read("word/document.xml").decode("utf-8")
    print(tag, "How to write:", xml.count("How to write"), "QuantumGuard:", xml.count("QuantumGuard"), "Metev:", xml.count("Metev"), "w:p count:", xml.count("<w:p "))