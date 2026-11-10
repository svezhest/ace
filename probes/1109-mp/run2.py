import json,sys,os,threading,queue,time
sys.path.insert(0,"/Users/user/Projects/nrhsi")
from nrhsi.researcher import cfg as RC, model as M, policy as POL
OUT='out2.jsonl'; POL.apply_stand("default")
done={(r['id'],r['k']) for r in map(json.loads,open(OUT))} if os.path.exists(OUT) else set()
q=queue.Queue(); lock=threading.Lock()
for b in json.load(open('battery2.json')):
    if (b['id'],b['k']) not in done and (len(sys.argv)<2 or b['k']<=int(sys.argv[1])): q.put(b)
def work():
    while True:
        try: b=q.get_nowait()
        except queue.Empty: return
        seed=81100+b['k']*1000+int(b['obs']); t=time.time(); msgs=list(b['messages'])
        resp,err=M.chat(msgs,RC.TEMP,seed); ch=(resp or {}).get('choices') or [{}]
        txt=err or (ch[0].get('message') or {}).get('content') or ''; first=None
        if ch[0].get('finish_reason')=='length':
            first=txt; what='src/hooks.py' if b['obs']=='08' else '`run` function'
            r2,e2=M.chat(msgs+[{"role":"assistant","content":txt},{"role":"user","content":f"Your reply was cut off at the length limit. Write the final {what} now, in one ```python block."}],RC.TEMP,seed)
            txt=e2 or ((((r2 or {}).get('choices') or [{}])[0].get('message')) or {}).get('content') or ''
        with lock:
            open(OUT,'a').write(json.dumps(dict(id=b['id'],k=b['k'],seed=seed,sec=round(time.time()-t,1),fr=ch[0].get('finish_reason'),first=first,answer=txt),ensure_ascii=False)+'\n')
            print(b['id'],b['k'],round(time.time()-t),len(txt),flush=True)
ts=[threading.Thread(target=work) for _ in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]; print('done')
