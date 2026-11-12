"""Какими инструментами рабочей копии пользуется писатель: python3 probes/1112/tools_used.py GLOB…
Строка на сессию: число вызовов bash и сколько из них — runs.py steps / runs.py show / rerun.py N / rerun.py --at /
свой python / чтение src / чтение ядра перепрогона."""
import glob
import json
import os
import re
import sys

P = {"steps": r"runs\.py steps", "show": r"runs\.py show", "rerun": r"tests/rerun\.py \d+(?!\s+--at)", "at": r"--at",
     "own": r"python3 -c|python3 - ?<<|python3 <<", "src": r"(cat|sed|grep|head|tail)\b[^|;&]*src/", "core": r"rerun_core"}
print(f"{'сессия':<30} bash " + " ".join(f"{k:>5}" for k in P))
for g in sys.argv[1:]:
    for p in sorted(glob.glob(g)):
        c = []
        for x in (json.loads(l) for l in open(p)):
            if x.get("type") != "turn":
                continue
            for t in x.get("tool_calls") or []:
                a = t.get("arguments") or {}
                a = json.loads(a) if isinstance(a, str) else a
                if t["name"] == "bash":
                    c.append(str(a.get("command") or ""))
        print(f"{os.path.basename(p)[:-6]:<30} {len(c):>4} " + " ".join(f"{sum(bool(re.search(v, s)) for s in c):>5}" for v in P.values()))
