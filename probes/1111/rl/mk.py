"""RL (11.11): ответ проверки на правку с новой сводкой повтора вместо записанной.
python3 probes/1111/rl/mk.py LOG TURN WORK OUT [UNDO_TURN] — берёт записанный ответ на edit хода TURN из LOG и заменяет в нём
вывод tests/rerun.py на сводку editor/rerun.py текущей ветки, посчитанную на src из WORK. UNDO_TURN: правка этого
(более позднего) хода сначала откатывается на копии src — чтобы src был таким, как после хода TURN."""
import json
import shutil
import subprocess
import sys
import tempfile

log, turn, work, out = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
T = {x["i"]: x for x in map(json.loads, open(log)) if x.get("type") == "turn"}
shown = [r["shown"] for r in T[turn]["results"] if r.get("name") == "edit"][-1]
src = tempfile.mkdtemp() + "/src"
shutil.copytree(work + "/src", src)
if len(sys.argv) > 5:
    for c in T[int(sys.argv[5])]["tool_calls"]:
        if c["name"] == "edit":
            a = c["arguments"] if isinstance(c["arguments"], dict) else json.loads(c["arguments"])
            f = src[:-3] + a["path"]
            s = open(f).read()
            assert s.count(a["new_string"]) == 1
            open(f, "w").write(s.replace(a["new_string"], a["old_string"]))
bench = "app" if "app" in open(work + "/tests/rerun.py").read().split("worker(")[1][:8] else "alf"
rep = subprocess.run([sys.executable, "editor/rerun.py", "--bench", bench, "--src", src, "--logs", work + "/logs",
                      "--old", work + "/tests/orig_src"], capture_output=True, text=True).stdout.rstrip("\n")
a, b = "python3 tests/rerun.py prints:\n", "\n\nCheck against the observation:"
i, j = shown.index(a) + len(a), shown.index(b)
open(out, "w").write(shown[:i] + rep + shown[j:])
print(out, len(shown), "->", len(shown) - (j - i) + len(rep))
