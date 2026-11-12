"""Разбор развилки `roll.py --stop checked`: python3 probes/1112/fork_edits.py OUT.jsonl…
Строка на ответ: на каком ходу после развилки правка, условия новой правки, что ответил перепрогон (сколько удачных и
проваленных прогонов идут иначе) и первая строка проверки по тикету. В конце — счёт: правка меняет прогон тикета и не
меняет удачные / меняет удачные / не действует / правки нет."""
import json
import re
import sys

for path in sys.argv[1:]:
    tot = {"чисто": 0, "задевает удачные": 0, "не действует": 0, "нет правки": 0, "падает": 0}
    print("==", path)
    for o in map(json.loads, open(path)):
        if not o.get("edit"):
            tot["нет правки"] += 1
            print(f"#{o['k']} нет правки ({o.get('end')}, ходов {len(o['turns'])})")
            continue
        a = json.loads(o["edit"]) if isinstance(o["edit"], str) else o["edit"]
        cond = [l.strip() for l in (a.get("new_string") or "").splitlines() if re.match(r"\s*(if|elif|while)\b", l)][:3]
        s = o.get("checked") or ""
        m = re.search(r"(\d+) go(?:es)? differently from the log: (\d+) passed runs? and (\d+) failed", s)
        chk = (re.search(r"Check against the observation:\n([^\n]*)", s) or [None, ""])[1]
        if not s.startswith("Applied"):
            kind, what = "нет правки", s[:80].replace("\n", " ")
        elif "Traceback" in s.split("Check against")[0] and "crash" in s:
            kind, what = "падает", ""
        elif chk.startswith("Failed"):
            kind, what = ("падает" if "crashes" in chk else "не действует"), ""
        elif m and int(m.group(2)) > 0:
            kind, what = "задевает удачные", f"удачных иначе {m.group(2)}, проваленных {m.group(3)}"
        else:
            kind, what = "чисто", (f"удачных иначе 0, проваленных {m.group(3)}" if m else "")
        tot[kind] += 1
        print(f"#{o['k']} ход +{len(o['turns'])} | {kind} {what} | {' ⏎ '.join(cond)[:260]}")
    print("   итог:", ", ".join(f"{k} {v}" for k, v in tot.items() if v))
