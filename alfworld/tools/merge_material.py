"""Дописать логи прогона runs/<tag> в view_v3/logs после уже лежащих (run_N нумеруются дальше), с проверкой хэша src.
python3 -I tools/merge_material.py material1"""
import json, shutil, sys, hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
tag = sys.argv[1]
run = ROOT / "runs" / tag
logs = ROOT / "view_v3" / "logs"
def src_hash(src):
    h = hashlib.sha256()
    for p in sorted(Path(src).glob("*")):
        if p.is_file():
            h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]
info = json.loads((run / "run.json").read_text())
assert info["src_hash"] == src_hash(ROOT / "view_v3" / "src") == src_hash(run / "src"), "src differs"
assert info["hint_level"] == 0
rows = [json.loads(l) for l in (logs / "results.jsonl").read_text().splitlines() if l.strip()]
base = max(r["run"] for r in rows)
new = [json.loads(l) for l in (run / "logs" / "results.jsonl").read_text().splitlines() if l.strip()]
meta = {json.loads(l)["run"]: json.loads(l) for l in (run / "meta.jsonl").read_text().splitlines()}
mp = ROOT / "runs" / "view_logs_map.json"
m = json.loads(mp.read_text()) if mp.exists() else {}
for r in sorted(new, key=lambda r: r["run"]):
    n = base + r["run"]
    shutil.copyfile(run / "logs" / f"run_{r['run']}.jsonl", logs / f"run_{n}.jsonl")
    rows.append({"run": n, "ok": r["ok"], "reason": r["reason"]})
    m[str(n)] = {"tag": tag, "run": r["run"], "game": meta[r["run"]]["game"]}
(logs / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
mp.write_text(json.dumps(m, indent=1))
print(base, len(new), sum(not r["ok"] for r in rows), "failed of", len(rows))
