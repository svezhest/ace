"""Подстановки editor/fork.py на заглушке: --last, --sub, --note меняют ровно своё место. Модель не вызывается
(F.chat подменён), стенд не трогается.
python3 probes/1110/forkcheck_subs.py LOG T
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, f"{ROOT}/editor")
import fork as FK  # noqa: E402

log, T = sys.argv[1], sys.argv[2]
got = {}
FK.F.chat = lambda ms, temp, seed, tools: (got.update(ms=json.loads(json.dumps(ms)), tools=tools, seed=seed), (None, "stub"))[1]
FK.F.apply_stand = lambda name: None


def run(*extra):
    sys.argv = ["fork", log, "--turn", T, "--n", "1", *extra]
    sys.stdout, keep = open(os.devnull, "w"), sys.stdout
    try:
        FK.main()
    finally:
        sys.stdout = keep
    return got["ms"], [t["function"]["name"] for t in got["tools"]], got["seed"]


base, tools, seed = run()
assert base == FK.history(FK.load(log), int(T))
last = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
last.write("REPLACED ANSWER")
last.close()
ms, _, _ = run("--last", last.name)
d = [i for i, (x, y) in enumerate(zip(base, ms)) if x != y]
print("--last:", "ok" if len(ms) == len(base) and d == [len(base) - 1] and ms[-1] == {**base[-1], "content": "REPLACED ANSWER"} else f"BAD {d}")
old = "fails fewer tasks"
n = sum((m.get("content") or "").count(old) for m in base)
ms, _, _ = run("--sub", old, "XX")
d = [i for i, (x, y) in enumerate(zip(base, ms)) if x != y]
ok = len(ms) == len(base) and all(ms[i] == {**base[i], "content": base[i]["content"].replace(old, "XX")} for i in d) \
    and d == [i for i, m in enumerate(base) if old in (m.get("content") or "")]
print(f"--sub: {'ok' if ok else 'BAD'}; {n} вхождений в сообщениях {d} (роли {[base[i]['role'] for i in d]})")
ms, _, _ = run("--note", "NOTE TEXT")
print("--note:", "ok" if ms[:-1] == base and ms[-1] == {"role": "user", "content": "NOTE TEXT"} else "BAD")
ms, t2, _ = run("--final")
print("--final:", "ok" if ms == base and t2 == tools[1:] and tools[0] == "bash" else "BAD", t2)
print("seed по умолчанию:", seed)
