import json,sys,urllib.request,concurrent.futures as cf
# cond.py OUT N BUDGET PROMPTFILE
out,n,budget,pf=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
prompt=open(pf).read()
def one(k):
    body={"model":"ornith15-9b","temperature":0.6,"seed":1000+k,"max_tokens":budget+1500,"enable_thinking":True,"thinking_budget":budget,
          "messages":[{"role":"user","content":prompt}]}
    req=urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions",data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer x"})
    with urllib.request.urlopen(req,timeout=1800) as r: resp=json.load(r)
    m=resp["choices"][0]["message"]
    return {"k":k,"content":m.get("content"),"reasoning":m.get("reasoning") or m.get("reasoning_content") or "","usage":resp.get("usage"),"finish":resp["choices"][0].get("finish_reason")}
with cf.ThreadPoolExecutor(4) as ex: rs=list(ex.map(one,range(n)))
with open(out,"w") as f:
    for r in rs: f.write(json.dumps(r,ensure_ascii=False)+"\n")
for r in rs: print(f"#{r['k']} think={len(r['reasoning'])} fin={r['finish']}: {(r['content'] or '').strip()}\n")
