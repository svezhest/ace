"""Replay of logged model replies through a view's src/ and the benchmark: is the conversation the same?

  .venv/bin/python tools/replay.py --logs view_v3/logs --tasks runs/material_tasks_seed1.json --src view_v3/src
For each run: the model's replies from the log are given back in order (stub model, no LLM), and the
conversation that comes out is compared with the log, message by message; also ok/reason. A reply is
logged as the harness kept it (cut after the first ```python block, + "\\n\\n"); a reply without a
code block is logged as reply + "\\n\\n", so that is taken off for the replay."""
import argparse
import concurrent.futures as cf
import json
import multiprocessing as mp
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def messages_of(path):
    rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    return [r["message"] for r in rows if "message" in r] if rows and "event" in rows[0] else rows


def raw_reply(m):
    c = m.get("content") or ""
    if "```python\n" not in c and c.endswith("\n\n"):
        c = c[:-2]
    return {**m, "content": c}


def one(job):
    sys.path.insert(0, str(ROOT / "runner"))
    import run
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "data").symlink_to(run.APPWORLD / "data")
        job = dict(job, appworld_root=tmp, env_log=str(Path(tmp) / "env.log"))
        r = run.play(job)
    got = [e["message"] for e in r["events"] if "message" in e]
    want = job["want"]
    first = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), None)
    if first is None and len(got) != len(want):
        first = min(len(got), len(want))
    return {"run": job["run"], "same": first is None, "first_diff": first, "n": (len(got), len(want)),
            "reason": r["reason"], "ok": r["ok"], "end": r["meta"]["end"], "honest": r["meta"]["honest"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--runs", nargs="*", type=int)
    a = ap.parse_args()
    tasks = json.loads(Path(a.tasks).read_text())
    res = {json.loads(x)["run"]: json.loads(x) for x in (Path(a.logs) / "results.jsonl").read_text().splitlines()}
    jobs = []
    tpl = (Path(a.logs).parent / "src" / "starting_prompt.md").read_text()
    n_prompt = len(re.findall("(USER|ASSISTANT|SYSTEM):\n", tpl, flags=re.IGNORECASE))
    for f in sorted(Path(a.logs).glob("run_*.jsonl"), key=lambda p: int(p.stem.split("_")[1])):
        run = int(f.stem.split("_")[1])
        if a.runs and run not in a.runs:
            continue
        want = messages_of(f)
        n0 = n_prompt  # the prompt's messages (demo turns included) come before the first model reply
        jobs.append({"run": run, "task": tasks[run - 1], "experiment": f"replay_{run}", "src": str(Path(a.src).resolve()),
                     "fake": [raw_reply(m) for m in want[n0:] if m["role"] == "assistant"], "gen": None,
                     "hint_level": 0, "wall_limit": 3600, "want": want})
    bad = 0
    with cf.ProcessPoolExecutor(a.workers, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as pool:
        for r in pool.map(one, jobs):
            old = res[r["run"]]
            same_res = (old["ok"], old["reason"]) == (r["ok"], r["reason"])
            bad += not (r["same"] and same_res)
            print(json.dumps({**r, "old": [old["ok"], old["reason"]], "same_result": same_res}), flush=True)
    print(f"{len(jobs) - bad}/{len(jobs)} identical")


if __name__ == "__main__":
    main()
