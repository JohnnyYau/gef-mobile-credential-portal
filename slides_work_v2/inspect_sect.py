import zipfile, re, pathlib
p = r"C:\Users\johnn\Downloads\Template_Learning_Summary.docx"
z = zipfile.ZipFile(p)
xml = z.read("word/document.xml").decode("utf-8")
# locate sectPr occurrences with index
for m in re.finditer(r"<w:sectPr[ >]", xml):
    s=max(0,m.start()-120); e=min(len(xml),m.end()+400)
    print("---- sectPr @", m.start())
    print(xml[s:e].replace("\n"," ")[:500])
print("PARAS:", xml.count("<w:p "), "TABLES:", xml.count("<w:tbl>"))