"""Чувствительность правки к своим числам (без модели): python3 probes/1112/sens.py МЕТКА=WORK…
Для каждого целого числа в изменённых строках src/harness.py рабочей копии — варианты «на единицу меньше» и «на
единицу больше»; каждый вариант перепрогоняется на прогонах вида. Класс варианта: чисто (прогон тикета меняется,
удачные идут как в логе) / задевает удачные / не действует / падает. Строка на правку: сколько вариантов остались
чистыми. Вид и тикет — вход № 1 (app_r1, run 1)."""
import ast
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile

M = "/Users/user/Projects/nrhsi"
VIEW, RR, TICKET = f"{M}/runs/typed_1111/app_r1", f"{M}-wt/check-keep/editor/rerun.py", "1"
ok = {str(json.loads(l)["run"]): bool(json.loads(l).get("ok")) for l in open(f"{VIEW}/logs/results.jsonl")}


def cls(src):
    r = subprocess.run([sys.executable, RR, "--bench", "app", "--src", src, "--logs", f"{VIEW}/logs", "--json"], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return "падает"
    if any(x and x["kind"] == "crash" for x in d.values()):
        return "падает"
    hit = [k for k, x in d.items() if x and ok[k] and not (x.get("event") or "").startswith("reworded")]
    return "задевает удачные" if hit else "чисто" if d.get(TICKET) else "не действует"


for arg in sys.argv[1:]:
    name, w = arg.split("=", 1)
    new = open(f"{w}/src/harness.py").read()
    old = open(f"{VIEW}/src/harness.py").read()
    changed = {j + 1 for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, old.splitlines(), new.splitlines()).get_opcodes()
               if tag in ("replace", "insert") for j in range(j1, j2)}
    lits = [n for n in ast.walk(ast.parse(new)) if isinstance(n, ast.Constant) and type(n.value) is int and n.lineno in changed]
    lines = new.splitlines(keepends=True)
    res = []
    for n in lits:
        for v in (n.value - 1, n.value + 1):
            if v < 0:
                continue
            L = list(lines)
            row = L[n.lineno - 1]
            L[n.lineno - 1] = row[:n.col_offset] + str(v) + row[n.end_col_offset:]
            t = tempfile.mkdtemp(dir=os.environ.get("SENS_TMP"))
            shutil.copytree(f"{w}/src", f"{t}/src")
            open(f"{t}/src/harness.py", "w").write("".join(L))
            res.append((n.lineno, n.value, v, cls(f"{t}/src")))
            shutil.rmtree(t)
    base = cls(f"{w}/src")
    c = sum(r[3] == "чисто" for r in res)
    print(f"{name:<26} сама: {base:<17} чисел {len(lits)}, вариантов {len(res)}, чистых {c}" + (f" ({100 * c // len(res)} %)" if res else ""))
    for r in res:
        if r[3] != "чисто":
            print(f"      строка {r[0]}: {r[1]} → {r[2]}: {r[3]}")
