"""Что smoke добавляет к перепрогону: на всех состояниях src из ev_states.py — падает ли smoke и падает ли перепрогон,
меняет ли правка то, что smoke показывает (сравнение с исходным src).
  python3 probes/1112/smoke_cover.py BENCH VIEW STATES.jsonl"""
import json, os, shutil, subprocess, sys, tempfile, collections
from concurrent.futures import ThreadPoolExecutor
bench, view, states = sys.argv[1:4]
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev_states as ES
SM = os.path.join(ROOT, "nrhsi/editor/smoke", bench + ".py")
src0 = ES.read_src(os.path.join(view, "src"))
rows = {}
for l in open(states):
    r = json.loads(l); rows.setdefault(r["state"], r)
files = {}
for r in rows.values():
    if r["state"] not in files:
        files[r["state"]] = ES.chain(os.path.join(ROOT, r["log"]), src0)[r["n"] - 1][1]

def smoke(f):
    with tempfile.TemporaryDirectory() as t:
        os.makedirs(f"{t}/tests"); shutil.copy(SM, f"{t}/tests/smoke.py")
        for rel, text in f.items():
            os.makedirs(os.path.dirname(f"{t}/{rel}"), exist_ok=True); open(f"{t}/{rel}", "w").write(text)
        p = subprocess.run([sys.executable, "tests/smoke.py"], cwd=t, capture_output=True, text=True, timeout=300)
        return p.stdout + p.stderr

base = smoke(src0)
with ThreadPoolExecutor(6) as ex:
    out = dict(zip(files, ex.map(smoke, files.values())))
c = collections.Counter()
for h, r in rows.items():
    d = r["div"]
    rc = "*" in d or any(v and v["kind"] == "crash" for v in d.values())
    s = out[h]
    sc = "Traceback" in s or "failed" in s.split("\n")[1] if len(s.split("\n")) > 1 else "Traceback" in s
    sc = "Traceback" in s
    c[("перепрогон падает" if rc else "перепрогон цел", "smoke падает" if sc else ("smoke другой" if s != base else "smoke как до правки"))] += 1
for k, v in sorted(c.items()): print(v, k)
