"""Шаг 6 тикета 10.11: первые три вызова записанных сессий (сверка «пересказ против дела»).
python3 probes/1110/s6/first3.py LOG...   (модель не вызывается)
"""
import json
import sys

for path in sys.argv[1:]:
    out = []
    for line in open(path):
        r = json.loads(line)
        if r.get("type") != "turn":
            continue
        for c in r["tool_calls"] or [{"function": {"name": "-", "arguments": "{}"}}]:
            f = c.get("function", c)
            a = f["arguments"]
            a = json.loads(a) if isinstance(a, str) else a
            out.append(f["name"] + ": " + (a.get("command") or a.get("path") or "")[:110].replace("\n", "⏎"))
        if r["i"] >= 3:
            break
    print(path.split("/")[-1])
    for o in out:
        print("   ", o)
