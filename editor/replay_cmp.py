"""Сравнение двух каталогов проигрышей editor/replay.py (A и B): логи сессий, копии вида и diff должны совпасть.
Время (ходов и в заголовках diff) и трассы ошибок харнесса (в них номера строк кода) не сравниваются.

  python3 editor/replay_cmp.py A B
"""
import glob
import json
import os
import sys


def no_cache(x):
    """Счётчик кэша в пробном запросе к стенду (запись meta) от кода не зависит."""
    if isinstance(x, dict):
        return {k: no_cache(v) for k, v in x.items() if k != "cached_tokens"}
    return [no_cache(v) for v in x] if isinstance(x, list) else x


def norm(path):
    out = []
    for r in map(json.loads, open(path)):
        if r.get("type") == "meta":
            r = no_cache(r)
        if r.get("type") == "error":
            r["traceback"] = True
        for res in r.get("results") or []:
            if "harness_error" in res:
                res["harness_error"] = True
        out.append(r)
    return out


def files(d):
    out = {}
    for top, dirs, fs in os.walk(d):
        dirs[:] = [x for x in dirs if x != "__pycache__" and not x.startswith(".")]
        for f in fs:
            if not f.startswith(".") and not f.endswith(".summary.json"):
                p = os.path.join(top, f)
                data = open(p, "rb").read()
                if f.endswith(".diff"):      # в заголовках diff — время изменения файлов
                    data = b"\n".join(x for x in data.split(b"\n") if not x.startswith((b"--- ", b"+++ ")))
                out[os.path.relpath(p, d)] = data
    return out


a, b = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/")
bad = n = 0
for home in sorted(glob.glob(f"{a}/*/")):
    name = os.path.basename(home.rstrip("/"))
    for la in sorted(glob.glob(f"{home}logs/*.jsonl")):
        lb, n = la.replace(a, b, 1), n + 1
        ra, rb = norm(la), norm(lb) if os.path.exists(lb) else None
        if ra != rb:
            bad += 1
            i = next((i for i, (x, y) in enumerate(zip(ra, rb or [])) if x != y), min(len(ra), len(rb or [])))
            print(f"DIFF {name}: log record {i + 1} of {len(ra)}/{len(rb or [])}")
    for sub in ("work", "out"):
        fa, fb = files(f"{home}{sub}"), files(f"{b}/{name}/{sub}")
        d = sorted(k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k))
        if d:
            bad += 1
            print(f"DIFF {name}: {sub}/: {', '.join(d[:6])}")
print(f"{n} sessions, {bad} differences")
sys.exit(1 if bad else 0)
