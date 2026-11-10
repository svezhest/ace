"""Серия базы: процесс сессий по логам. python3 probes/1110/base/proc.py HOME   (модель не вызывается)
Строка на сессию: ходов; вызовов bash; на каком вызове bash первая применённая правка (b= — сколько bash было до неё);
правок применено / попыток; ответы проверки тикета по порядку (O — все строки Ok, F — есть Failed; в скобках первая
буква причины: n — нет эффекта, k — keep, c — падение, t — только тексты / только код); чем кончилась; пик промпта.
"""
import glob
import json
import os
import sys


def kind(lines):
    if all(x.startswith("Ok") for x in lines):
        return "O"
    why = ""
    for x in lines:
        if x.startswith("Failed"):
            why += ("c" if "crashes" in x else "n" if "no effect" in x else "k" if "which passed" in x else "t")
    return f"F({why})"


for p in sorted(glob.glob(f"{sys.argv[1]}/*/logs/*_s*.jsonl")):
    recs = [json.loads(line) for line in open(p)]
    end = next((r for r in recs if r.get("type") == "end"), None)
    bash = edits = tried = 0
    first, checks, fin = None, [], False
    for r in recs:
        if r.get("type") == "ticket_check":
            checks.append(kind(r["lines"]))
        if r.get("type") != "turn":
            continue
        for c, x in zip(r["tool_calls"], r.get("results") or []):
            if c["name"] == "bash":
                bash += 1
            elif c["name"] == "edit":
                tried += 1
                if (x.get("edit") or {}).get("applied"):
                    edits += 1
                    if first is None:
                        first = (r["i"], bash)
            elif c["name"] == "finish":
                fin = True
    name = os.path.basename(p)[:-6]
    if not end:
        print(f"{name:18} идёт: ходов {sum(r.get('type') == 'turn' for r in recs)}, bash {bash}")
        continue
    s = end["stats"]
    print(f"{name:18} ходов {s['turns']:2} bash {s['bash_calls']:2} первая правка: "
          + (f"ход {first[0]:2} b={first[1]:2}" if first else "нет        ")
          + f" правок {edits}/{tried} проверки {' '.join(checks) or '-'} | {'finish' if fin else end['reason']} | пик {s['max_prompt']}")
