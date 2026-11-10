"""K4: 9B ищет условие на шагах с инструментами test и answer (answer — с проверкой).

  python3 k4.py OUT.jsonl N BUDGET MAXTURNS VIEW OBSFILE FAIL KEEP
  python3 k4.py selftest 0 0 0 VIEW OBSFILE FAIL KEEP [EXPR...]

VIEW — каталог вида с logs/run_N.jsonl; OBSFILE — вход писателя (берётся абзац «## Observation (problem)»);
FAIL, KEEP — номера прогонов из тикета.
"""
import collections
import concurrent.futures as cf
import json
import sys
import time
import urllib.request

out, n, budget, maxt = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
VIEW, OBSFILE, FAIL, KEEP = sys.argv[5].rstrip("/") + "/", sys.argv[6], int(sys.argv[7]), int(sys.argv[8])
URL = "http://127.0.0.1:8081/v1/chat/completions"
Step = collections.namedtuple("Step", "action observation")
SAFE = {k: __builtins__.__dict__[k] for k in (
    "len", "any", "all", "range", "set", "min", "max", "sum", "tuple", "list", "enumerate", "zip", "reversed",
    "sorted", "str", "int", "bool", "abs", "dict")}


def steps(run):
    ev = [json.loads(line) for line in open(f"{VIEW}logs/run_{run}.jsonl")]
    acts, res = {}, []
    for e in ev:
        m = e.get("message") or {}
        if e.get("event") == "model":
            for c in m.get("tool_calls") or []:
                try:
                    acts[c["id"]] = json.loads(c["function"]["arguments"]).get("action", "")
                except Exception:
                    acts[c["id"]] = ""
        elif e.get("event") == "env" and m.get("role") == "tool":
            res.append(Step(acts.get(m.get("tool_call_id"), ""), m["content"].split(" AVAILABLE ACTIONS:")[0].strip()))
    return tuple(res)


R = {FAIL: steps(FAIL), KEEP: steps(KEEP)}


def listing(run):
    return "\n".join(f"{i} {s.action} → {s.observation[:100]}{'…' if len(s.observation) > 100 else ''}"
                     for i, s in enumerate(R[run], 1))


def hits(expr):
    """-> ({run: [номера шагов]}, None) или (None, текст ошибки)."""
    res = {}
    for run, ss in R.items():
        hit = []
        for i in range(len(ss)):
            try:
                if eval(expr, {"__builtins__": SAFE, "step": ss[i], "earlier": ss[:i]}):
                    hit.append(i + 1)
            except Exception as ex:
                at = f" (earlier has {i} steps at step {i + 1})" if isinstance(ex, IndexError) else ""
                return None, f"Error at step {i + 1} of run {run}: {type(ex).__name__}: {ex}{at}"
        res[run] = hit
    return res, None


def kind(run):
    return "failed" if run == FAIL else "passed"


def test(expr):
    res, err = hits(expr)
    if err:
        return err
    return "\n".join(f"run {run} ({kind(run)}, {len(R[run])} steps): true at {len(h)} steps"
                     + (f": {', '.join(map(str, h))}" if h else "") for run, h in res.items())


def gate(expr):
    """-> (принято ли, текст ответа)."""
    res, err = hits(expr)
    if err:
        return False, f"Not accepted. {err}"
    if res[KEEP]:
        return False, (f"Not accepted: the condition is true at {len(res[KEEP])} steps of run {KEEP}, which passed: "
                       f"{', '.join(map(str, res[KEEP]))}.")
    if not res[FAIL]:
        return False, f"Not accepted: the condition is not true at any step of run {FAIL}."
    return True, "Accepted."


obs = open(OBSFILE).read().split("## Observation (problem)\n", 1)[1].split("\n\nCode:", 1)[0].strip()
PROMPT = f"""An observation from a study of an agent's failed runs:

{obs}

The steps of run {FAIL} (number, action → answer):
{listing(FAIL)}

The steps of run {KEEP}, which passed (number, action → answer):
{listing(KEEP)}

---
The harness will be changed so that it notices this problem while a run is going. At each step its code has the current step and the earlier steps of the same run, and nothing else. The same code will run on other tasks, with other objects and actions, and should notice the same problem there.

Find the condition on the current step and the earlier steps that holds at the steps of run {FAIL} where the problem shows and does not hold at any step of run {KEEP}. `test` checks a condition on both runs. When a condition does this, hand it in with `answer`, together with one or two sentences that state it in words, exactly enough to be checked step by step; these sentences will be added to the observation."""
NAMES = ("Names in the expression: `step` — the current step, with `step.action` and `step.observation` (strings); "
         "`earlier` — the earlier steps of the same run as a tuple, oldest first: `earlier[-1]` is the step right "
         "before the current one, `earlier[-2]` the one before that.")
T_TEST = {"type": "function", "function": {
    "name": "test",
    "description": f"Evaluate a Python expression at every step of run {FAIL} and run {KEEP} and report the steps "
                   f"where it is true. {NAMES}",
    "parameters": {"type": "object", "properties": {"condition": {"type": "string", "description": "a Python expression"}},
                   "required": ["condition"]}}}
T_ANSWER = {"type": "function", "function": {
    "name": "answer",
    "description": "Hand in the condition and the sentences that state it in words. The condition is checked on both "
                   "runs as in `test`.",
    "parameters": {"type": "object", "properties": {
        "condition": {"type": "string", "description": "the Python expression, as in `test`"},
        "statement": {"type": "string", "description": "one or two sentences that state the condition in words"}},
        "required": ["condition", "statement"]}}}


def call(ms, k, tools):
    body = {"model": "ornith15-9b", "temperature": 0.6, "seed": 3000 + k, "max_tokens": budget + 1500,
            "enable_thinking": True, "thinking_budget": budget, "messages": ms, "tools": tools}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.load(r)["choices"][0]["message"]


def one(k):
    ms, log, t0 = [{"role": "user", "content": PROMPT}], [], time.time()
    accepted = None
    for t in range(maxt):
        last = t == maxt - 1
        try:
            m = call(ms, k, [T_ANSWER] if last else [T_TEST, T_ANSWER])
        except Exception as ex:
            log.append({"turn": t + 1, "error": repr(ex)[:300]})
            break
        tcs = m.get("tool_calls") or []
        rs = len(m.get("reasoning") or m.get("reasoning_content") or "")
        a = {"role": "assistant", "content": m.get("content") or ""}
        if tcs:
            a["tool_calls"] = tcs
        ms.append(a)
        if not tcs:
            log.append({"turn": t + 1, "reasoning": rs, "say": m.get("content"), "calls": []})
            ms.append({"role": "user", "content": "Reply with a tool call: `test` or `answer`."})
            continue
        calls = []
        for c in tcs:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"]["arguments"])
                expr = args["condition"]
            except Exception as ex:
                args, expr, res = c["function"]["arguments"], None, f"Error: bad arguments: {ex}"
            else:
                if name == "answer":
                    ok, res = gate(expr)
                    if ok and accepted is None:
                        accepted = {"condition": expr, "statement": args.get("statement"), "turn": t + 1,
                                    "hits": hits(expr)[0]}
                elif name == "test":
                    res = test(expr)
                else:
                    res = f"Error: no tool named {name}."
            if t == maxt - 2 and c is tcs[-1]:
                res += "\n\nThis was the last check. Hand in with `answer` now."
            calls.append({"name": name, "args": args, "result": res})
            ms.append({"role": "tool", "tool_call_id": c["id"], "content": res})
        log.append({"turn": t + 1, "reasoning": rs, "say": m.get("content"), "calls": calls})
        if accepted:
            break
    return {"k": k, "accepted": accepted, "turns": log, "sec": round(time.time() - t0)}


if __name__ == "__main__":
    if out == "selftest":
        print(f"run {FAIL}: {len(R[FAIL])} steps; run {KEEP}: {len(R[KEEP])} steps; prompt {len(PROMPT)} chars")
        for e in sys.argv[9:]:
            print("T:", e)
            print("  ", test(e).replace("\n", "\n   "))
            print("   gate:", gate(e))
        sys.exit()
    with cf.ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(one, range(n)))
    with open(out, "w") as f:
        for r in rs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for r in rs:
        print(f"=== #{r['k']} turns={len(r['turns'])} sec={r['sec']} accepted={'turn %d' % r['accepted']['turn'] if r['accepted'] else 'no'}")
        for t in r["turns"]:
            if "error" in t:
                print("   ERROR", t["error"])
                continue
            if not t["calls"]:
                print(f"   t{t['turn']} think={t['reasoning']} (no call): {(t['say'] or '')[:160]!r}")
            for c in t["calls"]:
                e = c["args"].get("condition") if isinstance(c["args"], dict) else str(c["args"])
                print(f"   t{t['turn']} think={t['reasoning']} {c['name']}: {str(e)[:220]}")
                print(f"        => {c['result'].replace(chr(10), ' | ')[:230]}")
        if r["accepted"]:
            print("   STATEMENT:", r["accepted"]["statement"])
