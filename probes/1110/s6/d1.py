"""Шаг 7 тикета 10.11, точка D1: на что уходят вызовы bash первых трёх ходов (прокаты базы из ST6V).
python3 probes/1110/s6/d1.py runs/fk_1110/s6/0   (модель не вызывается)
Команда разбирается на части по ';', '&&', '||'; часть относится к первому подходящему классу.
"""
import json
import re
import sys
from collections import Counter

NAMED = {"05": (["starting_prompt.md"], ["run_6", "run_12"]),
         "06": (["starting_prompt.md", "hook_types.py", "hooks.py", "harness.py"], ["run_11"]),
         "08": (["harness.py", "hooks.py"], ["run_40"]),
         "09": (["harness.py", "starting_prompt.md"], ["run_8"])}


def cls(part, nn):
    files, logs = NAMED[nn]
    if "README" in part:
        return "README"
    if re.search(r"python3 tests/(rerun|runs|smoke)\.py", part):
        return "запуск tests"
    if "logs/" in part:
        return "лог из входа" if any(x in part for x in logs) else "другой лог или results"
    if "tests/" in part:
        return "чтение tests/"
    if "src/" in part:
        if re.search(r"\bls\b|\bwc\b|\bfind\b", part) and not re.search(r"\b(cat|sed|grep|head|tail|nl|awk)\b", part):
            return "ls, wc"
        return "файл из входа" if any(x in part for x in files) else "другой файл src/"
    if re.search(r"^\s*(ls|wc|find|pwd|echo)\b", part):
        return "ls, wc"
    return "прочее"


for nn in sorted(NAMED):
    c, calls, sess = Counter(), [], 0
    for line in open(f"{sys.argv[1]}/{nn}.roll.jsonl"):
        r = json.loads(line)
        sess += 1
        n = 0
        for t in r["turns"]:
            for call in t["calls"]:
                if call["name"] != "bash":
                    c[call["name"]] += 1
                    continue
                n += 1
                for part in re.split(r";|&&|\|\|", json.loads(call["arguments"]).get("command", "")):
                    if part.strip() and not part.strip().startswith("echo"):
                        c[cls(part, nn)] += 1
        calls.append(n)
    print(nn, f"сессий {sess}, вызовов bash за 3 хода: {sorted(calls)}", dict(c.most_common()))
