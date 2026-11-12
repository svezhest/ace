"""EV1, разметка входа № 1: где правка расходится с логом, был ли заблокированный шаг повтором и дал ли он в логе новый
вывод. Повтор кода, который в логе дал вывод иной, чем его прежнее исполнение (например, упал, потом прошёл), — законный
шаг; повтор с тем же выводом — цикл. Только для разметки (подсказка мне), оценщику не подаётся.

  python3 probes/1112/ev_legit.py STATES.jsonl VIEW > OUT.json"""
import json
import os
import sys

states, view = sys.argv[1], sys.argv[2]
steps = {}
for f in os.listdir(f"{view}/logs"):
    if not f.startswith("run_"):
        continue
    ev = [json.loads(l) for l in open(f"{view}/logs/{f}")]
    cur, call_code = None, {}
    seq = []
    for i, e in enumerate(ev):
        if e["event"] == "model":
            cur = e["call"]
        elif e["event"] == "bridge" and e.get("call") == "execute":
            out = next((x["message"]["content"] for x in ev[i + 1:] if x["event"] == "env"), "")
            seq.append((cur, e["code"].strip(), out))
    steps[f[4:-6]] = seq


def judge(run, call):
    seq = steps[run]
    k = next((j for j, s in enumerate(seq) if s[0] == call - 1), None)
    if k is None:
        return "not-a-step"
    _, code, out = seq[k]
    prev = [s for s in seq[:k] if s[1] == code]
    if not prev:
        return "new-code"
    return "loop" if prev[-1][2] == out else "legit-repeat"


res = {}
for l in open(states):
    r = json.loads(l)
    if r["state"] in res:
        continue
    d = {}
    for run, v in r["div"].items():
        if v and run.isdigit() and v["kind"] == "model" and v["call"]:
            d[run] = (v["call"], judge(run, v["call"]))
        elif v:
            d[run] = (v.get("call"), v["kind"])
    res[r["state"]] = d
json.dump(res, sys.stdout)
