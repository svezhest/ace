import json,sys,os,threading,queue,time
sys.path.insert(0,"/Users/user/Projects/nrhsi")
from nrhsi.researcher import cfg as RC, model as M, policy as POL
S=sys.argv[1]; N=int(sys.argv[2]); OUT=S+'/'+sys.argv[3]; only=sys.argv[4].split(',') if len(sys.argv)>4 else None
POL.apply_stand("default")
done={(r['id'],r['k']) for r in map(json.loads,open(OUT))} if os.path.exists(OUT) else set()
q=queue.Queue(); lock=threading.Lock()
B=json.load(open(S+'/battery.json'))
for k in range(1,N+1):
    for b in B:
        if (b['id'],k) not in done and (not only or b['id'] in only): q.put((b,k))
def work():
    while True:
        try: b,k=q.get_nowait()
        except queue.Empty: return
        seed=71100+k*1000+int(b['obs'])
        t=time.time(); resp,err=M.chat([{"role":"user","content":b['text']}],RC.TEMP,seed)
        ch=(resp or {}).get('choices') or [{}]
        txt=err or (ch[0].get('message') or {}).get('content') or ''
        first=None
        if ch[0].get('finish_reason')=='length':
            first=txt; what='src/hooks.py' if b['obs']=='08' else '`run` function'
            resp2,err2=M.chat([{"role":"user","content":b['text']},{"role":"assistant","content":txt},{"role":"user","content":f"Your reply was cut off at the length limit. Write the final {what} now, in one ```python block."}],RC.TEMP,seed)
            ch2=(resp2 or {}).get('choices') or [{}]
            txt=err2 or (ch2[0].get('message') or {}).get('content') or ''
        with lock:
            open(OUT,'a').write(json.dumps(dict(id=b['id'],k=k,seed=seed,sec=round(time.time()-t,1),fr=ch[0].get('finish_reason'),usage=(resp or {}).get('usage'),first=first,answer=txt),ensure_ascii=False)+'\n')
            print(b['id'],k,round(time.time()-t),len(txt),flush=True)
ts=[threading.Thread(target=work) for _ in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
