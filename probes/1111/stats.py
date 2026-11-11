"""Сводка поведения писателя по сессиям: python3 probes/1111/stats.py МЕТКА=GLOB [МЕТКА=GLOB ...]
На группу: медианы и разброс по сессиям — ход первой правки, bash до первой правки, вызовы bash с чтением кода стенда
(tests/rerun_core.py, tests/rerun.py, tests/smoke.py — чтение, не запуск), свои скрипты до первой правки, ходы с текстом."""
import glob
import json
import re
import statistics as st
import sys

READ = re.compile(r"(cat|sed|grep|head|tail|nl|less|wc)\b[^|;&]*tests/(rerun_core|rerun|smoke|runs)\.py|tests/rerun_core\.py")
OWN = re.compile(r"python3 -(c)? ?|python3 <<|python3 - ?<<")


def one(path):
    T = [x for x in map(json.loads, open(path)) if x.get("type") == "turn"]
    r = dict(turns=len(T), fe=None, bash=0, bash_fe=0, stand=0, own_fe=0, text=0)
    for x in T:
        r["text"] += bool((x.get("content") or "").strip())
        for k in x.get("tool_calls") or []:
            a = k.get("arguments") or {}
            a = json.loads(a) if isinstance(a, str) else a
            if k["name"] == "edit" and r["fe"] is None:
                r["fe"] = x["i"]
            if k["name"] != "bash":
                continue
            cmd = a.get("command") or ""
            r["bash"] += 1
            r["stand"] += bool(READ.search(cmd))
            if r["fe"] is None:
                r["bash_fe"] += 1
                r["own_fe"] += bool(re.search(r"python3 (-c|- ?<<|<<)", cmd))
    return r


def med(v):
    v = [x for x in v if x is not None]
    return "—" if not v else f"{st.median(v):g} ({min(v)}–{max(v)})"


print("группа | сессий | ходов | ход 1-й правки | bash до 1-й правки | bash всего | чтение кода стенда | свой скрипт до правки | ходов с текстом")
for arg in sys.argv[1:]:
    name, g = arg.split("=", 1)
    R = [one(p) for p in sorted(glob.glob(g))]
    R = [r for r in R if r["turns"]]
    if not R:
        print(name, "| 0"); continue
    print(name, "|", len(R), "|", " | ".join(med([r[k] for r in R]) for k in ("turns", "fe", "bash_fe", "bash", "stand", "own_fe", "text")))
