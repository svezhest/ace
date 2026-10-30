"""Run the harness in <view>/src on AppWorld tasks and write <view>/logs.

Everything here is outside src/: the benchmark process (env_server.py, one per episode, in AppWorld's
venv), model transport, budget, logging, results. A full copy of the run (src snapshot, logs, private
per-run meta with the benchmark's evaluation, worker/gateway env, AppWorld outputs) goes to runs/<tag>/;
<view>/logs is then replaced by this run's logs, so the logs always come from the code in <view>/src.

  python run.py --split train --n 20 --seed 1 --workers 2 --tag material1
  python run.py --fake '["..."]' --tasks ID --tag fake          # stub model, no LLM
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import multiprocessing as mp
import os
import random
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT.parent))   # stand.py — профиль стенда
import stand as STAND                  # noqa: E402
APPWORLD = Path.home() / "Projects" / "appworld"           # AppWorld root (data) and its venv
APPWORLD_PY = APPWORLD / ".venv" / "bin" / "python"
def src_hash(src):
    h = hashlib.sha256()
    for p in sorted(Path(src).glob("*")):
        if p.is_file():
            h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(url, payload=None, timeout=900):
    data = None if payload is None else json.dumps(payload).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
        return json.loads(r.read())


class Benchmark:
    """The AppWorld process for one episode."""

    def __init__(self, task_id, experiment, root, log_path):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        env = dict(os.environ, APPWORLD_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1",
                   PYTHONHASHSEED="0")  # set/dict print order of the task's code: reproducible
        self.log = open(log_path, "w")
        self.proc = subprocess.Popen([str(APPWORLD_PY), str(HERE / "env_server.py"), "--task-id", task_id,
                                      "--experiment", experiment, "--port", str(self.port)],
                                     cwd=str(root), env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 300
        while True:
            try:
                post(self.url + "/ready", timeout=5)
                break
            except Exception:
                if self.proc.poll() is not None or time.time() > deadline:
                    self.close()
                    raise RuntimeError(f"benchmark did not start, see {log_path}")
                time.sleep(0.5)

    def finish(self):
        return post(self.url + "/finish", {})

    def close(self):
        if self.proc.poll() is None:
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()


def hint(evaluation, level):
    """Benchmark feedback for results.jsonl beyond ok/reason (ablation axis; 0 = none).
    1: how many of the benchmark's checks passed. 2: + the failed checks' requirements."""
    if level <= 0 or not evaluation:
        return None
    n, fails = evaluation["num_tests"], evaluation["failures"]
    text = f"{n - len(fails)} of {n} checks passed"
    if level >= 2 and fails:
        text += "; failed: " + " | ".join(" ".join(f["requirement"].split()) for f in fails)
    return text


def play(job):
    sys.dont_write_bytecode = True
    sys.path[:0] = [job["src"], str(HERE)]
    import bridge
    import harness
    from fake import Fake
    from llm import Client, EpisodeEnd

    t0, reason, detail, messages, evaluation, completed = time.time(), None, "", None, None, False
    bench = Benchmark(job["task"], job["experiment"], job["appworld_root"], job["env_log"])
    try:
        ep = bridge.Episode(bench.url)
        if job["fake"] is not None:
            llm = Fake(job["fake"], bridge.STEP_LIMIT)
        else:
            g = job["gen"]
            llm = Client(g["url"], g["model"], bridge.STEP_LIMIT, job["wall_limit"], seed=g["seed"],
                         temperature=g["temperature"], max_tokens=g["max_tokens"])
        try:
            messages = harness.run(ep, llm)
        except EpisodeEnd as e:
            reason, detail = e.reason, e.detail
        except Exception:
            reason, detail = "harness error", traceback.format_exc(limit=5)
        completed = post(bench.url + "/completed")
        evaluation = bench.finish()
    finally:
        bench.close()
    if not isinstance(messages, list):
        messages = llm.conversation or []
    if evaluation["success"]:
        reason = "success"
    elif completed:
        reason = "wrong result"
    elif reason is None:
        reason = "step limit" if len(llm.calls) >= bridge.STEP_LIMIT else "harness stopped early"
    as_json = [json.dumps(m, sort_keys=True) for m in messages]
    append_only = all([json.dumps(m, sort_keys=True) for m in r] == as_json[:len(r)] for r in llm.requests)
    prompt_tokens = [c["prompt_tokens"] or 0 for c in llm.calls]
    ok = reason == "success"
    return {"run": job["run"], "ok": ok, "reason": reason, "hint": hint(evaluation, job["hint_level"]),
            "messages": messages,
            "meta": {"run": job["run"], "task": job["task"], "ok": ok, "reason": reason, "detail": detail,
                     "completed": completed, "sec": round(time.time() - t0, 1), "model_calls": len(llm.calls),
                     "max_prompt_tokens": max(prompt_tokens, default=0),
                     "completion_tokens": sum(c["completion_tokens"] or 0 for c in llm.calls),
                     "append_only": append_only, "evaluation": evaluation, "calls": llm.calls}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default=str(ROOT / "view"))
    ap.add_argument("--split", default="train", choices=["train", "val"])
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tasks", nargs="*", help="explicit task ids (must be in train or val)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--hint-level", type=int, default=0, help="0: ok/reason only; 1: + checks passed; 2: + failed checks")
    ap.add_argument("--stand", default="default", help="profile in stands/: model, gateway, generation parameters")
    ap.add_argument("--wall-limit", type=int, default=3600, help="seconds per episode")
    ap.add_argument("--fake", help="JSON script for the stub model (no LLM calls)")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--no-publish", action="store_true", help="do not replace <view>/logs")
    a = ap.parse_args()

    view, out = Path(a.view).resolve(), ROOT / "runs" / a.tag
    if out.exists():
        sys.exit(f"{out} exists")
    src = view / "src"
    splits = json.loads((ROOT / "splits.json").read_text())
    allowed = set(splits["train"]) | set(splits["val"])
    tasks = a.tasks or random.Random(a.seed).sample(splits[a.split], a.n)
    if not set(tasks) <= allowed:
        sys.exit(f"tasks outside train/val: {sorted(set(tasks) - allowed)}")
    P = STAND.load(a.stand)
    g = STAND.gen(P, "executor", "appworld")
    stand = {"stand": STAND.meta(P, STAND.check(P, ["executor"]) if a.fake is None else None), "gen": g}

    out.mkdir(parents=True)
    shutil.copytree(src, out / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (out / "logs").mkdir()
    (out / "env").mkdir()
    aw_root = out / "appworld"
    aw_root.mkdir()
    (aw_root / "data").symlink_to(APPWORLD / "data")
    info = {"tag": a.tag, "src_hash": src_hash(out / "src"), "split": a.split, "seed": a.seed, "n": len(tasks),
            "tasks": tasks, "hint_level": a.hint_level, "fake": a.fake, "workers": a.workers,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"), **stand}
    (out / "run.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info), flush=True)

    jobs = [{"run": i + 1, "task": t, "experiment": f"run_{i + 1}", "appworld_root": str(aw_root),
             "env_log": str(out / "env" / f"run_{i + 1}.log"), "src": str(out / "src"),
             "fake": json.loads(a.fake) if a.fake else None, "gen": g,
             "hint_level": a.hint_level, "wall_limit": a.wall_limit}
            for i, t in enumerate(tasks)]
    results, t0 = [], time.time()
    with cf.ProcessPoolExecutor(a.workers, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as pool:
        futs = {pool.submit(play, j): j for j in jobs}
        for f in cf.as_completed(futs):
            try:
                r = f.result()
            except Exception:
                j = futs[f]
                r = {"run": j["run"], "ok": False, "reason": "runner error", "hint": None, "messages": [],
                     "meta": {"run": j["run"], "task": j["task"], "detail": traceback.format_exc()}}
            results.append(r)
            with open(out / "logs" / f"run_{r['run']}.jsonl", "w") as fh:
                for m in r["messages"]:
                    fh.write(json.dumps(m, ensure_ascii=False) + "\n")
            with open(out / "meta.jsonl", "a") as fh:
                fh.write(json.dumps(r["meta"], ensure_ascii=False) + "\n")
            m = r["meta"]
            print(f"[{time.time() - t0:7.0f}s] run {r['run']:3d} {m.get('task')} ok={r['ok']!s:5} {r['reason']:<18} "
                  f"calls={m.get('model_calls')} ctx={m.get('max_prompt_tokens')} sec={m.get('sec')}", flush=True)

    results.sort(key=lambda r: r["run"])
    with open(out / "logs" / "results.jsonl", "w") as fh:
        for r in results:
            row = {"run": r["run"], "ok": r["ok"], "reason": r["reason"]}
            if a.hint_level > 0:
                row["hint"] = r["hint"]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {"ok": sum(r["ok"] for r in results), "n": len(results), "wall_sec": round(time.time() - t0, 1)}
    (out / "summary.json").write_text(json.dumps(summary))
    print(json.dumps(summary), flush=True)

    if not a.no_publish:
        if src_hash(src) != info["src_hash"]:
            sys.exit("src/ changed during the run; logs not published to the view")
        logs = view / "logs"
        shutil.rmtree(logs, ignore_errors=True)
        shutil.copytree(out / "logs", logs)


if __name__ == "__main__":
    main()
