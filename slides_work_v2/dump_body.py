import docx
from docx.oxml.ns import qn
d = docx.Document(r"C:\Users\johnn\Downloads\Template_Learning_Summary.docx")
body = d.element.body
for i, ch in enumerate(body):
    tag = ch.tag.split("}")[1]
    if tag == "p":
        txt = "".join(t.text or "" for t in ch.iter(qn("w:t")))
        has_sect = ch.find(qn("w:pPr")+"/"+qn("w:sectPr")) is not None
        print(f"{i:3d} P  sect={int(has_sect)} | {txt[:60]}")
    elif tag == "tbl":
        print(f"{i:3d} TBL")
    elif tag == "sectPr":
        print(f"{i:3d} FINAL-SECTPR")