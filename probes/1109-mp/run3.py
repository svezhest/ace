import json,sys,os,threading,queue,time
sys.path.insert(0,"/Users/user/Projects/nrhsi")
import stand as ST
from nrhsi.researcher import cfg as C, model as M
g=ST.gen(ST.load('thinking'),'agent')
C.URL,C.MODEL,C.TEMP=g["url"]+"/chat/completions",g["model"],g["temperature"]
C.MAX_GEN,C.THINKING,C.THINK_BUDGET=g["max_tokens"],g["thinking"],g["think_budget"]
print(C.URL,C.THINKING,C.THINK_BUDGET,C.MAX_GEN,flush=True)
N=int(sys.argv[1]); OUT='out3.jsonl'; arms=('08_A','08_C','08_R','01_A','01_R')
done={(r['id'],r['k']) for r in map(json.loads,open(OUT))} if os.path.exists(OUT) else set()
q=queue.Queue(); lock=threading.Lock()
B=[b for b in json.load(open('battery.json')) if b['id'] in arms]
for k in range(1,N+1):
    for b in B:
        if (b['id'],k) not in done: q.put((b,k))
def msg(resp):
    ch=(resp or {}).get('choices') or [{}]; m=ch[0].get('message') or {}
    return m.get('content') or '', m.get('reasoning') or m.get('reasoning_content') or '', ch[0].get('finish_reason'), (resp or {}).get('usage')
def work():
    while True:
        try: b,k=q.get_nowait()
        except queue.Empty: return
        seed=71100+k*1000+int(b['obs']); t=time.time()
        resp,err=M.chat([{"role":"user","content":b['text']}],C.TEMP,seed)
        txt,rs,fr,us=msg(resp); txt=err or txt; first=None
        if fr=='length':
            first=txt; what='src/hooks.py' if b['obs']=='08' else '`run` function'
            r2,e2=M.chat([{"role":"user","content":b['text']},{"role":"assistant","content":txt or "(no answer yet)"},{"role":"user","content":f"Your reply was cut off at the length limit. Write the final {what} now, in one ```python block."}],C.TEMP,seed)
            txt,rs2,_,_=msg(r2); txt=e2 or txt
        with lock:
            open(OUT,'a').write(json.dumps(dict(id=b['id'],k=k,seed=seed,sec=round(time.time()-t,1),fr=fr,usage=us,reasoning=rs,first=first,answer=txt),ensure_ascii=False)+'\n')
            print(b['id'],k,round(time.time()-t),fr,(us or {}).get('completion_tokens_details'),len(txt),flush=True)
ts=[threading.Thread(target=work) for _ in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]; print('done')
