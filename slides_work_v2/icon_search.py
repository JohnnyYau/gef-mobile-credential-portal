import json
p=r"C:\Users\johnn\AppData\Local\Doubao\User Data\Default\.doubao\agent_mode\workspace\.skills\ppt\references\xml\iconpark-index.json"
data=json.load(open(p,encoding="utf-8"))
paths=[]
def walk(o):
    if isinstance(o,dict):
        for v in o.values(): walk(v)
    elif isinstance(o,list):
        for v in o: walk(v)
    elif isinstance(o,str) and o.startswith("iconpark/"): paths.append(o)
walk(data)
for w in ["school","building","bank","institution","academic","college","university","teacher"]:
    hits=[x for x in paths if w in x]
    if hits: print(w, hits[:6])