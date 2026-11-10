import json,sys,urllib.request,concurrent.futures as cf,collections
# k2.py OUT N BUDGET MAXTURNS
out,n,budget,maxt=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4])
V="/private/tmp/claude-501/-Users-user-Projects-itmo/0b27b398-da99-461f-b5a5-02754fadcd5d/scratchpad/fk/h_g9/work/g9/"
Step=collections.namedtuple("Step","action observation")
def steps(run):
    ev=[json.loads(l) for l in open(f"{V}logs/run_{run}.jsonl")]; acts={}; res=[]
    for e in ev:
        m=e.get("message") or {}
        if e.get("event")=="model":
            for c in m.get("tool_calls") or []:
                try: acts[c["id"]]=json.loads(c["function"]["arguments"]).get("action","")
                except Exception: acts[c["id"]]=""
        elif e.get("event")=="env" and m.get("role")=="tool":
            res.append(Step(acts.get(m.get("tool_call_id"),""), m["content"].split(" AVAILABLE ACTIONS:")[0].strip()))
    return tuple(res)
FAIL,KEEP=40,28
R={FAIL:steps(FAIL),KEEP:steps(KEEP)}
def test(expr):
    lines=[]
    for run,ss in R.items():
        hit=[]
        for i in range(len(ss)):
            try:
                if eval(expr,{"__builtins__":{"len":len,"any":any,"all":all,"range":range,"set":set,"min":min,"max":max,"sum":sum,"tuple":tuple,"list":list,"enumerate":enumerate,"zip":zip,"reversed":reversed,"sorted":sorted,"str":str,"int":int,"bool":bool,"abs":abs},"step":ss[i],"earlier":ss[:i]}): hit.append(i+1)
            except Exception as ex:
                return f"Error at step {i+1} of run {run}: {type(ex).__name__}: {ex}"
        lines.append(f"run {run} ({'failed' if run==FAIL else 'passed'}, {len(ss)} steps): true at {len(hit)} steps" + (f": {', '.join(map(str,hit))}" if hit else ""))
    return "\n".join(lines)
obs=open("/Users/user/Projects/nrhsi/runs/typed_1110/in/08_v_rr.txt").read().split("## Observation (problem)\n",1)[1].strip()
HDR="(number @line, action → first line of the answer):\n"
PROMPT=f"""An observation from a study of an agent's failed runs:

{obs}

The steps of run {FAIL} {HDR}{open("steps40.txt").read()}
The steps of run {KEEP}, which passed {HDR}{open("steps28.txt").read()}
---
The harness will be changed so that it notices this problem while a run is going. At each step its code has the current step and the earlier steps of the same run, and nothing else. The same code will run on other tasks, with other objects and actions, and should notice the same problem there.

Find the condition on the current step and the earlier steps that holds at the steps of run {FAIL} where the problem shows and does not hold at any step of run {KEEP}. You have the tool `test` to check a condition on both runs. When a condition you have checked does this, reply without a tool call: one or two sentences that state it in words, exactly enough to be checked step by step, to be added to the observation."""
TOOLS=[{"type":"function","function":{"name":"test","description":"Evaluate a Python expression at every step of run 40 and run 28 and report the steps where it is true. Names in the expression: `step` — the current step, with `step.action` and `step.observation` (strings); `earlier` — the tuple of the earlier steps of the same run, oldest first, each with `.action` and `.observation`.","parameters":{"type":"object","properties":{"condition":{"type":"string","description":"a Python expression, e.g. len(earlier) >= 1 and step.action == earlier[-1].action (check len(earlier) before indexing)"}},"required":["condition"]}}}]
def call(ms,k,tools=True):
    body={"model":"ornith15-9b","temperature":0.6,"seed":2000+k,"max_tokens":budget+1500,"enable_thinking":True,"thinking_budget":budget,"messages":ms}
    if tools: body["tools"]=TOOLS
    req=urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions",data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer x"})
    with urllib.request.urlopen(req,timeout=1800) as r: return json.load(r)["choices"][0]["message"]
def one(k):
    ms=[{"role":"user","content":PROMPT}]; tr=[]; final=None
    for t in range(maxt):
        m=call(ms,k,t<maxt-1); tcs=m.get("tool_calls") or []
        ms.append({"role":"assistant","content":m.get("content") or "","tool_calls":tcs} if tcs else {"role":"assistant","content":m.get("content") or ""})
        if not tcs: final=m.get("content"); break
        for c in tcs:
            try: e=json.loads(c["function"]["arguments"])["condition"]; r=test(e)
            except Exception as ex: e=c["function"]["arguments"]; r=f"Error: {ex}"
            tr.append((e,r)); ms.append({"role":"tool","tool_call_id":c["id"],"content":r})
    return {"k":k,"tests":tr,"final":final}
if __name__=="__main__":
    if out=="selftest":
        print(len(R[40]),len(R[28])); print(R[28][1:3]); print(test("len(earlier)>=2 and step==earlier[-2] and step!=earlier[-1]")); print(test("step in earlier")); sys.exit()
    with cf.ThreadPoolExecutor(4) as ex: rs=list(ex.map(one,range(n)))
    with open(out,"w") as f:
        for r in rs: f.write(json.dumps(r,ensure_ascii=False)+"\n")
    for r in rs:
        print(f"=== #{r['k']} tests={len(r['tests'])}")
        for e,res in r["tests"]: print("   T:",e[:200]); print("      ",res.replace("\n"," | ")[:260])
        print("   FINAL:",(r["final"] or "").strip()[:900])
