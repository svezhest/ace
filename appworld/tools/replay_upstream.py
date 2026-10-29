"""Replay upstream AppWorld runs through view/src + env_server and compare with what upstream sent.

For each task of an upstream experiment (appworld run with the simplified ReAct agent, lm_calls logged),
the logged model replies are fed back through our harness (stub model). Checked:
  - every request our harness sends == the upstream request (role + content of every message);
  - our final evaluation == upstream evaluations/<dataset>.json (success).
No model calls.

  .venv/bin/python -I tools/replay_upstream.py ~/Projects/appworld/experiments/outputs/ornith9b_react_dev dev
"""
import concurrent.futures as cf
import json
import multiprocessing as mp
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replay(args):
    exp_dir, task = args
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT / "view" / "src"), str(ROOT / "runner")]
    import bridge
    import harness
    from fake import Fake
    from llm import EpisodeEnd
    from run import APPWORLD, Benchmark

    calls = [json.loads(l) for l in open(Path(exp_dir) / "tasks" / task / "logs" / "lm_calls.jsonl")]
    want = [[{"role": m["role"], "content": m["content"]} for m in c["input"]["messages"]] for c in calls]
    replies = [c["output"]["choices"][0]["message"]["content"] if c["output"].get("choices") else None
               for c in calls]
    errors = [c["output"].get("error") for c in calls]
    if errors[-1]:  # upstream ended on a model error: replay up to it
        replies = replies[:-1]
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "data").symlink_to(APPWORLD / "data")
        bench = Benchmark(task, "replay", tmp, Path(tmp) / "env.log")
        try:
            llm = Fake(replies or [""], step_limit=len(replies))
            try:
                harness.run(bridge.Episode(bench.url), llm)
            except EpisodeEnd:
                pass
            ev = bench.finish()
        finally:
            bench.close()
    got = [[{"role": m["role"], "content": m["content"]} for m in r] for r in llm.requests]
    first_diff = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), None)
    return {"task": task, "calls_upstream": len(calls), "calls_replay": len(got), "upstream_error": bool(errors[-1]),
            "requests_equal": first_diff is None and len(got) == len(want) - bool(errors[-1]),
            "first_diff": first_diff, "success": ev["success"]}


def main():
    exp_dir, dataset = Path(sys.argv[1]).expanduser(), sys.argv[2]
    upstream = json.loads((exp_dir / "evaluations" / f"{dataset}.json").read_text())["individual"]
    tasks = sorted(upstream)
    out = ROOT / "runs" / f"_replay_{exp_dir.name}.jsonl"
    with cf.ProcessPoolExecutor(4, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as pool, \
            open(out, "w") as fh:
        for r in pool.map(replay, [(str(exp_dir), t) for t in tasks]):
            r["success_upstream"] = upstream[r["task"]]["success"]
            fh.write(json.dumps(r) + "\n")
            print(json.dumps(r), flush=True)
    rows = [json.loads(l) for l in open(out)]
    print(json.dumps({"tasks": len(rows), "requests_equal": sum(r["requests_equal"] for r in rows),
                      "success_equal": sum(r["success"] == r["success_upstream"] for r in rows),
                      "success": sum(r["success"] for r in rows),
                      "requests_compared": sum(r["calls_replay"] for r in rows)}))


if __name__ == "__main__":
    main()
