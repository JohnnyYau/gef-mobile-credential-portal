import json
p=r"C:\Users\johnn\AppData\Local\Doubao\User Data\Default\.doubao\agent_mode\workspace\.skills\ppt\references\xml\iconpark-index.json"
data=json.load(open(p,encoding="utf-8"))
def walk(o, acc):
    if isinstance(o, dict):
        for k,v in o.items(): walk(v,acc)
    elif isinstance(o, list):
        for v in o: walk(v,acc)
    elif isinstance(o,str):
        acc.append(o)
paths=[]; walk(data,paths)
want=["blockchain","check-one","robot","people-bottom-card","school","two-dimensional-code-two","doc-success","certificate"]
for w in want:
    hits=[x for x in paths if w in x]
    print(w, "->", hits[:3])