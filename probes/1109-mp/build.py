import json,sys
R="/Users/user/Projects/nrhsi"; S=sys.argv[1]
def meta(n): return json.loads(open(f"{R}/runs/wvar_1104/{n}/logs/wv_{n}.jsonl").readline())
def turns(n): return [json.loads(l) for l in open(f"{R}/runs/wvar_1104/{n}/logs/wv_{n}.jsonl")][1:]
def first_edit(n):
    for r in turns(n):
        if r.get('type')!='turn': continue
        for tc,res in zip(r.get('tool_calls') or [], r.get('results') or []):
            if tc['name']=='edit':
                a=json.loads(tc['arguments']); s=res.get('shown') or json.dumps(res)
                if isinstance(res,dict) and not res.get('shown'):
                    s=next((v for v in res.values() if isinstance(v,str) and 'Checks run' in v), s)
                return a, s[s.find('python3 tests/rerun.py prints:'):]
def code(view, files):
    return "\n\n## src/ as it is now\n\n" + "\n\n".join(f"src/{f}:\n```python\n{open(f'{R}/runs/plain_1106/{view}/src/{f}').read().rstrip()}\n```" for f in files)
out=[]
# ---------- 08 (alf_r1)
fu=meta('08_PK_s1')['first_user'].rstrip()
tail="\n\nChange src/ so that the agent fails fewer tasks."
assert fu.endswith(tail.strip()); body=fu[:-len(tail.strip())].rstrip()
keep="Run 28 passed and should go as in the log: there the harness already does what it should."
assert keep in body
c8=code('alf_r1',['harness.py','hooks.py'])
q8="\n\nWrite the new src/hooks.py in full, in one ```python block."
a,chk=first_edit('08_PK_s1')
F8="\n\n## An earlier attempt\n\nA colleague has already tried this in src/hooks.py:\n```python\n"+a['new_string'][a['new_string'].find('def on_post_step'):]+"\n```\nThe check after that edit printed:\n```\n"+chk.strip()+"\n```"
L=[json.loads(l) for l in open(S+'/ctx_dump.jsonl')]
sel=[c for c in L if c['step'] in (9,10) and c['output'].startswith('examine d') and 'look' in c['history']['last_actions'][7:8]][:2]
assert len(sel)==2, len(sel)
def cut(c):
    f=lambda s: s if len(s)<=60 else s[:57]+'…'
    c=dict(c); c['observation']=f(c['observation']); c['admissible']=c['admissible'][:2]+['…']
    h=dict(c['history']); h['last_actions']=['…']+h['last_actions'][-3:]; h['last_observations']=['…']+[f(x) for x in h['last_observations'][-3:]]; c['history']=h
    return json.dumps(c,ensure_ascii=False)
C8="\n\n## ctx as on_post_step receives it\n\nFrom run 40, the calls after step 9 and after step 10 (long strings and lists are cut with …):\n```\n"+"\n".join(map(cut,sel))+"\n```"
R8=keep+' In run 28 the model sends "take candle 1 from countertop 1", "take candle 2 from countertop 1" and "inventory" several times between steps 8 and 17, the answers differ from time to time, and it then completes the task: these repeats belong to a passing run and should get no message from the harness.'
out+= [dict(id='08_A',obs='08',text=body+c8+q8), dict(id='08_C',obs='08',text=body+c8+C8+q8),
       dict(id='08_F',obs='08',text=body+c8+F8+q8), dict(id='08_R',obs='08',text=body.replace(keep,R8)+c8+q8)]
# ---------- 01 (app_r1)
fu=meta('01_PK_s1')['first_user'].rstrip(); body=fu[:-len(tail.strip())].rstrip()
keep="Run 8 passed and should go as in the log: there the harness already does what it should."
assert keep in body
c1=code('app_r1',['harness.py'])
q1="\n\nWrite the new `run` function of src/harness.py in full, in one ```python block (new helper functions, if you need them, go in the same block before it)."
a,chk=first_edit('01_PK_s1')
F1="\n\n## An earlier attempt\n\nA colleague has already tried this in src/harness.py: the line\n```python\n"+a['old_string'].split('\n')[0]+"\n```\nwas replaced with\n```python\n"+a['new_string'].split('\n')[0]+"\n```\nThe check after that edit printed:\n```\n"+chk.strip()+"\n```"
R1=keep+" In run 8 the model sends the code of step 7 again at step 9: at step 7 it failed with a NameError (spotify_access_token was not set yet), step 8 set the token, and at step 9 the same code ran and printed 17. Such a repeat belongs to a passing run and must still be executed."
out+= [dict(id='01_A',obs='01',text=body+c1+q1), dict(id='01_F',obs='01',text=body+c1+F1+q1), dict(id='01_R',obs='01',text=body.replace(keep,R1)+c1+q1)]
json.dump(out,open(S+'/battery.json','w'),ensure_ascii=False,indent=1)
for o in out: print(o['id'],len(o['text']))
print(out[2]['text'][-1500:]); print('=====',out[1]['text'][-1300:-60]); print('=====',out[5]['text'][-900:])
