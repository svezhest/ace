"""Ходы сессии писателя одной строкой на вызов: python3 probes/1111/moves.py LOG [знаков команды=110]
Для парного чтения двух сессий на одном входе: что вызвано на каждом ходу, сколько знаков текста и рассуждения."""
import json
import sys

N = int(sys.argv[2]) if len(sys.argv) > 2 else 110
for x in (json.loads(l) for l in open(sys.argv[1])):
    if x.get("type") != "turn":
        continue
    head = f"{x['i']:>2} т{len(x.get('content') or '')} р{len(x.get('reasoning') or '')}"
    for c in x.get("tool_calls") or [{"name": "—", "arguments": {}}]:
        a = c.get("arguments") or {}
        a = json.loads(a) if isinstance(a, str) else a
        what = a.get("command") or a.get("new_string") or a.get("summary") or ""
        print(head, c["name"], "|", str(what)[:N].replace("\n", " ⏎ "))
        head = " " * len(head)
