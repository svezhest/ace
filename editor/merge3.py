"""Слияние двух узлов от общего предка без модели: 3-way merge src/ по файлам (git merge-file).

  python3 editor/merge3.py BASE A B OUT [--markers]

OUT — вид (README.md из A, src/). Файл без конфликта — слитый; с конфликтом — версия A (база сравнения),
с --markers — с маркерами конфликта git (<<<<<<< a / ======= / >>>>>>> b): вход комбинатора (editor --arm merge).
Итог — OUT/merge.json: base, a, b, по файлу: clean | a-only | b-only | conflict (число конфликтов).
"""
import json
import os
import shutil
import subprocess
import sys

base, a, b, out = sys.argv[1:5]
markers = "--markers" in sys.argv[5:]
if os.path.exists(out):
    shutil.rmtree(out)
os.makedirs(f"{out}/src")
shutil.copy(f"{a}/README.md", out)
files = sorted((set(os.listdir(f"{a}/src")) | set(os.listdir(f"{b}/src"))) - {"__pycache__"})
res = {}
for f in files:
    pa, pb, po = f"{a}/src/{f}", f"{b}/src/{f}", f"{base}/src/{f}"
    if not os.path.exists(pb) or not os.path.exists(pa):     # файл есть только в одной ветке
        shutil.copy(pa if os.path.exists(pa) else pb, f"{out}/src/{f}")
        res[f] = "a-only" if os.path.exists(pa) else "b-only"
        continue
    o = po if os.path.exists(po) else os.devnull
    p = subprocess.run(["git", "merge-file", "-p", "-L", "a", "-L", "original", "-L", "b", pa, o, pb], capture_output=True)
    if p.returncode == 0 or markers:
        open(f"{out}/src/{f}", "wb").write(p.stdout)
        res[f] = "clean" if p.returncode == 0 else f"conflict ({p.returncode})"
    else:
        shutil.copy(pa, f"{out}/src/{f}")    # без --markers: при конфликте — версия a
        res[f] = f"conflict ({p.returncode})"
json.dump({"base": base, "a": a, "b": b, "files": res}, open(f"{out}/merge.json", "w"), indent=1)
print(json.dumps(res))
