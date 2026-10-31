"""Append the logs of runs/<tag> to view_v3/logs after the runs already there (run_N continue), checking the src hash.
.venv/bin/python -I tools/merge_material.py material1"""
import json, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runner"))
from run import src_hash  # noqa: E402

tag = sys.argv[1]
run, logs = ROOT / "runs" / tag, ROOT / "view_v3" / "logs"
info = json.loads((run / "run.json").read_text())
assert info["src_hash"] == src_hash(ROOT / "view_v3" / "src") == src_hash(run / "src"), "src differs"
assert info["hint_level"] == 0 and info["fake"] is None
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
    m[str(n)] = {"tag": tag, "run": r["run"], "task": meta[r["run"]]["task"]}
(logs / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
mp.write_text(json.dumps(m, indent=1))
print(base, len(new), sum(not r["ok"] for r in rows), "failed of", len(rows))
