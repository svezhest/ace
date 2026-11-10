import json,sys,os,re,shutil,subprocess
R="/Users/user/Projects/nrhsi"; S=sys.argv[1]; OUT=S+'/'+sys.argv[2]
CFG={'08':dict(bench='alf',view='alf_r1',ticket='40',keep='28'),'01':dict(bench='app',view='app_r1',ticket='1',keep='8')}
rows=[]
for r in map(json.loads,open(OUT)):
    obs=r['id'][:2]; c=CFG[obs]; V=f"{R}/runs/plain_1106/{c['view']}"
    d=f"{S}/src/{r['id']}_{r['k']}"; shutil.rmtree(d,ignore_errors=True); shutil.copytree(V+'/src',d)
    m=[];cur=None
    for ln in r['answer'].split('\n'):
        if cur is None and ln.strip().startswith('```py'): cur=[]
        elif cur is not None and ln.strip()=='```': m.append('\n'.join(cur)+'\n'); cur=None
        elif cur is not None: cur.append(ln)
    key='def on_post_step' if r['id'][:2]=='08' else 'def run('
    m=[x for x in m if key in x][-1:] or m
    res={r_['run']:r_['ok'] for r_ in map(json.loads,open(V+'/logs/results.jsonl'))}
    row=dict(id=r['id'],k=r['k'],cut=bool(r.get('first'))); rows.append(row)
    if not m: row['note']='no block'; continue
    blk=max(m,key=len)
    if obs=='08': open(d+'/hooks.py','w').write(blk)
    else:
        h=open(d+'/harness.py').read(); i=h.find('\ndef run(')
        if 'def run(' not in blk: row['note']='no run()'; continue
        open(d+'/harness.py','w').write(h[:i]+'\n'+blk)
    base=['python3',R+'/editor/rerun.py','--bench',c['bench'],'--src',d,'--logs',V+'/logs','--old',V+'/src']
    try:
        j=subprocess.run(base+['--json'],capture_output=True,text=True,timeout=300)
        t=subprocess.run(base,capture_output=True,text=True,timeout=300).stdout
        div=json.loads(j.stdout)
    except Exception as e: row['note']=f'rerun: {type(e).__name__} {j.stderr[-200:] if "j" in dir() else ""}'; continue
    open(d+'/rerun.txt','w').write(t)
    f=lambda x: None if x is None else (x['kind'][0]+str(x.get('call','')))
    row.update(ticket=f(div[c['ticket']]),keep=f(div[c['keep']]),
               passed=sum(1 for k,v in div.items() if v and res[int(k)]),failed=sum(1 for k,v in div.items() if v and not res[int(k)]),
               crash=sum(1 for v in div.values() if v and v['kind']=='crash'),raised='raised' in t)
for row in rows: print(json.dumps(row))
