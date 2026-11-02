"""Сколько применённых правок писателя не проверено: после них не было ни одного запуска tests/smoke.py.

  python3 editor/unchecked.py 'runs/tree_*_1101/*.edit/*/logs/*.jsonl'
"""
import collections
import glob
import json
import sys

c = collections.Counter()
for f in sorted(glob.glob(sys.argv[1])):
    ev = []   # ("edit", final) | ("smoke",)
    for line in open(f):
        d = json.loads(line)
        if d.get("type") != "turn":
            continue
        for tc, r in zip(d.get("tool_calls") or [], d.get("results") or []):
            name = tc.get("name") or tc.get("function", {}).get("name")
            args = tc.get("arguments") or tc.get("function", {}).get("arguments") or ""
            if name == "edit" and (r.get("edit") or {}).get("applied"):
                ev.append(("edit", d.get("final")))
            elif name == "bash" and "tests/smoke.py" in args:
                ev.append(("smoke",))
    for i, e in enumerate(ev):
        if e[0] == "edit":
            checked = any(x[0] == "smoke" for x in ev[i + 1:])
            c[("final" if e[1] else "main", "checked" if checked else "unchecked")] += 1
    c["sessions"] += 1
for k, v in sorted(c.items(), key=str):
    print(k, v)
