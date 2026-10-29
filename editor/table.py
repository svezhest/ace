"""Таблица механики по сессиям B1: python table.py [prefix=b1_]"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
pre = sys.argv[1] if len(sys.argv) > 1 else "b1_"


def end(p):
    for l in open(p):
        r = json.loads(l)
        if r.get("type") == "end":
            return r
    return None


rows = []
for s in sorted(glob.glob(f"{HERE}/out/{pre}*.summary.json")):
    sm = json.load(open(s))
    tag = sm["tag"]
    e = end(f"{HERE}/logs/{tag}.jsonl")
    p = end(f"{HERE}/logs/{tag}_p.jsonl") if sm["arm"] == "fix" else None
    ck = f"{HERE}/out/{tag}.check.json"
    ck = json.load(open(ck)) if os.path.exists(ck) else {}
    st = e["stats"]
    mins = st["model_sec"] / 60 + (p["stats"]["model_sec"] / 60 if p else 0)
    rows.append({
        "tag": tag, "bench": sm["bench"], "input": sm["input"], "arm": sm["arm"], "n_obs": sm["n_reports"],
        "props": p["stats"]["proposals"] if p else "", "edits": f"{st['edits_applied']}/{st['edits_attempted']}",
        "fail": ",".join(f"{k}:{v}" for k, v in sorted(st["edit_fail"].items())) or "-",
        "bash": f"{st['bash_calls']}" + (f"+{p['stats']['bash_calls']}" if p else ""),
        "denied": st["denied"] + (p["stats"]["denied"] if p else 0),
        "peak": max(st["max_prompt"], p["stats"]["max_prompt"] if p else 0),
        "min": round(mins, 1), "end": e["reason"] + (f" / p:{p['reason']}" if p else ""),
        "import": ck.get("import_ok"), "compile": len(ck.get("compile_errors", [])) if ck else None,
        "tests_broken": ",".join(t.replace("test_", "") for t in ck.get("tests_failed", [])) or "-",
    })
cols = ["bench", "input", "arm", "n_obs", "props", "edits", "fail", "bash", "denied", "peak", "min", "import",
        "compile", "tests_broken", "end"]
print("| " + " | ".join(cols) + " |")
print("|" + "---|" * len(cols))
for r in rows:
    print("| " + " | ".join(str(r[c]) for c in cols) + " |")
for arm in ("obs", "fix"):
    rs = [r for r in rows if r["arm"] == arm]
    a = sum(int(r["edits"].split("/")[1]) for r in rs)
    ok = sum(int(r["edits"].split("/")[0]) for r in rs)
    print(f"{arm}: sessions {len(rs)}, edits {ok}/{a}, min {round(sum(r['min'] for r in rs), 1)}, "
          f"peak max {max([r['peak'] for r in rs] or [0])}, broken-test sessions "
          f"{sum(r['tests_broken'] != '-' for r in rs)}")
