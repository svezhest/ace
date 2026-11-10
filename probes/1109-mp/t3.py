import sys,json
sys.path.insert(0,'/Users/user/Projects/nrhsi/editor'); import rerun as R
src,V,ticket=sys.argv[1],sys.argv[2],sys.argv[3]
res={str(r['run']):r['ok'] for r in map(json.loads,open(V+'/logs/results.jsonl'))}
new=R.worker('alf',src,V+'/logs')
ev=[json.loads(l) for l in open(f'{V}/logs/run_{ticket}.jsonl')]
acts=[]
for e in ev:
    if e['event']=='model':
        try: acts.append(json.loads(e['message']['tool_calls'][0]['function']['arguments']).get('action'))
        except Exception: acts.append('(no action)')
def said(h):
    if h.get('raised'): return 'raised '+h['raised']
    return json.dumps(h['out'],ensure_ascii=False)[:140] if h.get('out') is not None else None
t=new[ticket]; by={}
for h in t['hooks']:
    s=said(h)
    if s: by.setdefault(h['call']-1 if h['hook']=='on_post_step' else h['call'],[]).append(f"{h['hook']} -> {s}")
last=max([h['call'] for h in t['hooks']] or [1])-1
lines=[]
first=min(by) if by else None
lo,hi=(max(1,first-2),first) if first else (9,14)
for st in range(lo,min(hi,last,len(acts))+1):
    lines.append(f'  step {st} "{acts[st-1]}": '+('; '.join(by[st]) if st in by else 'all hooks returned None'))
n=sum(1 for st in by)
head=f"run {ticket} (failed), what the hooks returned, by step:\n"+"\n".join(lines)
if not by: head+=f"\n  in all {last} steps of run {ticket}: all hooks returned None"
elif t['div']: head+=f"\n  the replay of run {ticket} stops at step {first}: from there the run goes differently from the log"
p=[]
for r,tt in new.items():
    if res[r] and any(said(h) for h in tt['hooks']):
        c=min(h['call']-(1 if h['hook']=='on_post_step' else 0) for h in tt['hooks'] if said(h)); p.append(f"{r} (step {c})")
head+=f"\npassed runs where a hook returned something: "+(", ".join(p) if p else "none")+f" — {len(p)} of {sum(res.values())}"
print(head)
