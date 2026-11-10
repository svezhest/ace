import json,subprocess
S='.'; B={b['id']:b for b in json.load(open('battery.json'))}
A={(r['id'],r['k']):r for r in map(json.loads,open('out.jsonl'))}
W={'08':'src/hooks.py','01':'`run` function of src/harness.py'}
def conv(id,k):
    r=A[(id,k)]; m=[{"role":"user","content":B[id]['text']}]
    if r.get('first'):
        m+=[{"role":"assistant","content":r['first']},{"role":"user","content":f"Your reply was cut off at the length limit. Write the final {W[id[:2]].replace('src/hooks.py','src/hooks.py') if id[:2]=='08' else '`run` function'} now, in one ```python block."}]
    return m+[{"role":"assistant","content":r['answer']}]
def T2(obs,both):
    runs="the failed run described in the observation" + (" and for the steps of the passed run that the observation describes" if both else "")
    return (f"Check this code by hand before it goes in. For six consecutive steps of {runs}, write a line per step: what the code reads at that step (the actual values) and what it returns there. "
            f"If the lines show that it does not do what the observation needs, write the corrected {W[obs]} in full, in one ```python block; if they show that it does, repeat the code unchanged in one ```python block.")
T1={'08':"\n\nWork in this order. First, your condition in one line. Second, for six consecutive steps of the failed run described in the observation, a line per step: what the condition reads at that step (the actual values) and whether it is true there. Third, if these lines show the condition is not true where the observation needs it, change the condition and redo the lines. Last, the new src/hooks.py in full, in one ```python block.",
    '01':"\n\nWork in this order. First, your condition in one line. Second, for six consecutive steps of the failed run described in the observation and for the steps of the passed run that the observation describes, a line per step: what the condition reads at that step (the actual values) and whether it is true there. Third, if these lines show the condition is true where it should not be or not true where the observation needs it, change the condition and redo the lines. Last, the new `run` function of src/harness.py in full, in one ```python block (new helper functions, if you need them, go in the same block before it)."}
out=[]
for k in range(1,11):
    for id,both in (('08_A',False),('08_R',True),('01_A',False),('01_R',True)):
        out.append(dict(id=id+'_T2',k=k,obs=id[:2],messages=conv(id,k)+[{"role":"user","content":T2(id[:2],both)}]))
    t=subprocess.run(['python3','t3.py',f'src/08_A_{k}','/Users/user/Projects/nrhsi/runs/plain_1106/alf_r1','40'],capture_output=True,text=True).stdout.strip()
    assert t, k
    out.append(dict(id='08_A_T3',k=k,obs='08',messages=conv('08_A',k)+[{"role":"user","content":"This code was run on the recorded runs (the model's replies are taken from the logs):\n```\n"+t+"\n```\nIf this shows that the code does not do what the observation needs, write the corrected src/hooks.py in full, in one ```python block; if it shows that it does, repeat the code unchanged in one ```python block."}]))
    for id in ('08_A','01_R'):
        tx=B[id]['text']; q=tx[tx.rfind('\n\nWrite the new'):]
        out.append(dict(id=id+'_T1',k=k,obs=id[:2],messages=[{"role":"user","content":tx[:-len(q)]+T1[id[:2]]}]))
json.dump(out,open('battery2.json','w'),ensure_ascii=False)
print(len(out)); print(out[4]['messages'][-1]['content'][:1500]); print('---'); print(out[0]['messages'][-1]['content']); print('---',out[5]['messages'][0]['content'][-700:])
