"""Разбор докатов: python3 probes/1112/rolls.py HOME ХОД МЕТКА…   (МЕТКА — t1_fa, t1_base: логи HOME/logs/МЕТКА_r*.jsonl)
Строка на докат: ходов после развилки, правок и вызовов bash после неё, чем кончился, последняя проверка по тикету,
итог src/ рабочей копии — сколько проваленных и удачных прогонов вида идут иначе (и какие удачные)."""
import glob
import json
import os
import re
import subprocess
import sys

H, T = sys.argv[1], int(sys.argv[2])
PY = sys.executable
for tag in sys.argv[3:]:
    for log in sorted(glob.glob(f"{H}/logs/{tag}_r*.jsonl")):
        name = os.path.basename(log)[:-6]
        L = [json.loads(x) for x in open(log)]
        turns = [x for x in L if x.get("type") == "turn" and x["i"] >= T]
        calls = [c["name"] for x in turns for c in x.get("tool_calls") or []]
        end = [x for x in L if x.get("type") == "end"]
        checks = [x for x in L if x.get("type") == "ticket_check"]
        last = "; ".join(l.split(":")[0] + (" " + ",".join(re.findall(r"run (\d+)", l)[:1]) if "Failed" in l else "") for l in (checks[-1]["lines"] if checks else []))
        work = f"{H}/work/{name}"
        bench = re.search(r"R\.worker\('(\w+)'", open(f"{work}/tests/rerun.py").read()).group(1)
        r = subprocess.run([PY, "/Users/user/Projects/nrhsi/editor/rerun.py", "--bench", bench, "--src", f"{work}/src",
                            "--logs", f"{work}/logs", "--json"], capture_output=True, text=True)
        div = json.loads(r.stdout.strip().splitlines()[-1])
        ok = {str(json.loads(l)["run"]): bool(json.loads(l).get("ok")) for l in open(f"{work}/logs/results.jsonl")}
        f = [k for k, d in div.items() if d and not ok[k]]
        p = [k for k, d in div.items() if d and ok[k]]
        fin = "finish" if "finish" in calls else (end[-1].get("reason") or "end") if end else "идёт"
        print(f"{name} | ходов {len(turns)} | правок {calls.count('edit')} | bash {calls.count('bash')} | {fin} | {last} | провал {','.join(f) or '—'} / удачн {','.join(p) or '—'}")
