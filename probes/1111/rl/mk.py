"""RL (11.11): ответ проверки на правку с новой сводкой повтора — строки «-» (что было в логе) перед «+».
python3 probes/1111/rl/mk.py LOG TURN WORK OUT — берёт записанный ответ на edit хода TURN из LOG, строки «-» — из сводки
editor/rerun.py на WORK (ветка feature/rerun-log-line), вставляет их перед «  + user:» и пишет в OUT (для fork.py --last)."""
import json
import subprocess
import sys

log, turn, work, out = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
t = [x for x in map(json.loads, open(log)) if x.get("type") == "turn" and x["i"] == turn][0]
shown = [r["shown"] for r in t["results"] if r.get("name") == "edit"][-1]
rep = subprocess.run([sys.executable, "editor/rerun.py", "--bench", "app", "--src", work + "/src", "--logs", work + "/logs",
                      "--old", work + "/tests/orig_src"], capture_output=True, text=True).stdout
was = "".join(l + "\n" for l in rep.splitlines() if l.startswith("  - "))
assert was and shown.count("\n  + user:") == 1, (len(was), shown.count("\n  + user:"))
open(out, "w").write(shown.replace("\n  + user:", "\n" + was + "  + user:"))
print(out, len(shown), "->", len(shown) + len(was))
