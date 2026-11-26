import zipfile, re
p=r"C:\Users\johnn\Doubao\chats\2026-10-22\new-chat\GEF-mobile-project\Learning_Summary_draft.docx"
xml=zipfile.ZipFile(p).read("word/document.xml").decode("utf-8")
print("tbl:", xml.count("<w:tbl>"), "drawing:", xml.count("<w:drawing"), "sectPr:", xml.count("<w:sectPr"))
print("w:p total:", len(re.findall(r"<w:p[ >]", xml)))
rels=zipfile.ZipFile(p).read("word/_rels/document.xml.rels").decode("utf-8")
print("image rels:", re.findall(r'Id="(rId\d+)"[^>]*image', rels))