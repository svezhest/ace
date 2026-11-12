"""EV1: состояния src после каждой применённой правки в сессиях писателя и факты перепрогона на полном виде.

  python3 probes/1112/ev_states.py --bench app --view runs/full_1112/app_r1 --out OUT.jsonl LOG...

LOG — полный лог сессии писателя (meta + turn; логи докатов roll.py — тоже полные). Правки берутся из tool_calls
ходов, применённые — где results[i].edit.applied, и накладываются по порядку на src вида. На каждое состояние —
перепрогон всех прогонов вида ядром editor/rerun.py --json. Строка OUT: {log, turn, n (номер правки в сессии),
last (последняя применённая правка сессии), diff (unified против src вида), div: {run: {kind, call} | None}}.
Одинаковые состояния считаются один раз (кэш по содержимому src)."""
import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(ROOT, "editor", "rerun.py")


def read_src(d):
    out = {}
    for base, _, files in os.walk(d):
        if "__pycache__" in base:
            continue
        for f in files:
            p = os.path.join(base, f)
            out[os.path.relpath(p, os.path.dirname(d))] = open(p).read()   # ключ вида src/harness.py
    return out


def chain(log, src0):
    """[(turn, files)] после каждой применённой правки."""
    files, out = dict(src0), []
    for line in open(log):
        t = json.loads(line)
        if t.get("type") != "turn":
            continue
        for c, r in zip(t.get("tool_calls") or [], t.get("results") or []):
            if c.get("name") != "edit" or not (isinstance(r, dict) and (r.get("edit") or {}).get("applied")):
                continue
            a = json.loads(c["arguments"]) if isinstance(c["arguments"], str) else c["arguments"]
            rel = os.path.normpath(a["path"])
            if not rel.startswith("src/"):
                rel = "src/" + rel
            old, new = a["old_string"], a["new_string"]
            cur = files.get(rel, "")
            assert (old == "" and cur == "") or cur.count(old) == 1 or old == "", (log, t["i"], rel)
            files[rel] = new if old == "" else cur.replace(old, new, 1)
            out.append((t["i"], dict(files)))
    return out


def udiff(src0, files):
    d = []
    for rel in sorted(set(src0) | set(files)):
        a, b = src0.get(rel, ""), files.get(rel, "")
        if a != b:
            d += difflib.unified_diff(a.splitlines(True), b.splitlines(True), f"a/{rel}", f"b/{rel}", n=2)
    return "".join(d)


def replay(bench, view, files):
    with tempfile.TemporaryDirectory() as tmp:
        for rel, text in files.items():
            p = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(text)
        p = subprocess.run([sys.executable, CORE, "--bench", bench, "--src", os.path.join(tmp, "src"),
                            "--logs", os.path.join(view, "logs"), "--json"], capture_output=True, text=True, timeout=900)
    try:
        div = json.loads(p.stdout.strip().splitlines()[-1])
        return {r: (None if d is None else {"kind": d["kind"], "call": d["call"], "text": d["text"][:300]}) for r, d in div.items()}
    except Exception:  # noqa: BLE001
        tail = [l for l in (p.stderr or p.stdout).strip().splitlines() if l.strip()]
        return {"*": {"kind": "crash", "call": None, "text": tail[-1] if tail else ""}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--view", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("logs", nargs="+")
    a = ap.parse_args()
    src0 = read_src(os.path.join(a.view, "src"))
    rows, todo = [], {}
    for log in a.logs:
        try:
            ch = chain(log, src0)
        except (AssertionError, KeyError) as e:   # сессия шла на другом src вида: правка не ложится
            print(f"пропуск {log}: {e!r}"[:200])
            continue
        for n, (turn, files) in enumerate(ch, 1):
            h = hashlib.md5(json.dumps(files, sort_keys=True).encode()).hexdigest()
            todo[h] = files
            rows.append({"log": os.path.relpath(log, ROOT), "turn": turn, "n": n, "last": n == len(ch), "state": h,
                         "diff": udiff(src0, files)})
    with ThreadPoolExecutor(4) as ex:
        res = dict(zip(todo, ex.map(lambda f: replay(a.bench, a.view, f), todo.values())))
    with open(a.out, "w") as f:
        for r in rows:
            r["div"] = res[r["state"]]
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} правок, {len(todo)} разных состояний -> {a.out}")


if __name__ == "__main__":
    main()
