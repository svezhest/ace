"""Run the harness in <view>/src on ALFWorld games and write <view>/logs.

Everything here is outside src/: model transport, budget, logging, results. A full copy of the run
(src snapshot, logs, private per-run meta, worker env) goes to runs/<tag>/; <view>/logs is then
replaced by this run's logs, so the logs always come from the code currently in <view>/src.

  python run.py --view ../view --split train --n 8 --seed 1 --workers 4 --tag smoke1
  python run.py --view ../view --fake '["@first"]' --n 2 --tag fake   # stub model, no LLM
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import multiprocessing as mp
import os
import random
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data" / "alfworld"
WORKER_KEYS = ("QWEN_MAX_CONTEXT", "QWEN_PRESENCE_PENALTY", "QWEN_MAX_BATCH", "QWEN_BATCH_INVARIANT",
               "QWEN_PROMPT_CACHE", "QWEN_KV_BITS", "QWEN_MODEL")


def src_hash(src):
    h = hashlib.sha256()
    for p in sorted(Path(src).glob("*")):
        if p.is_file():
            h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def worker_env():
    """Sampling-relevant env of the live model worker (only whitelisted keys)."""
    try:
        pids = subprocess.run(["pgrep", "-f", "python worker.py"], capture_output=True, text=True).stdout.split()
        out = {}
        for pid in pids:
            env = subprocess.run(["ps", "eww", "-p", pid], capture_output=True, text=True).stdout.split()
            out[pid] = {k: v for k, _, v in (t.partition("=") for t in env) if k in WORKER_KEYS}
        return out
    except Exception as e:
        return {"error": repr(e)}


def play(job):
    sys.dont_write_bytecode = True
    sys.path[:0] = [job["src"], str(HERE)]
    import bridge
    import harness
    from fake import Fake
    from llm import Client, EpisodeEnd

    ep = bridge.Episode(job["game"], str(DATA))
    if job["fake"] is not None:
        llm = Fake(job["fake"], bridge.STEP_LIMIT)
    else:
        llm = Client(job["url"], job["model"], bridge.STEP_LIMIT, job["wall_limit"])
    t0, reason, detail, messages = time.time(), None, "", None
    try:
        messages = harness.run(ep, llm)
    except EpisodeEnd as e:
        reason, detail = e.reason, e.detail
    except Exception:
        reason, detail = "harness error", traceback.format_exc(limit=5)
    if not isinstance(messages, list):
        messages = llm.conversation or []
    if ep.won:
        reason = "success"
    elif reason is None:
        if ep.end_reason == "repeated action":
            reason = "repeated action"
        elif len(llm.calls) >= bridge.STEP_LIMIT:
            reason = "step limit"
        else:
            reason = "harness stopped early"
    hint = ep.hint(job["hint_level"]) if job["hint_level"] > 0 else None
    ep.close()
    as_json = [json.dumps(m, sort_keys=True) for m in messages]
    append_only = all([json.dumps(m, sort_keys=True) for m in r] == as_json[:len(r)] for r in llm.requests)
    prompt_tokens = [c["prompt_tokens"] or 0 for c in llm.calls]
    return {"run": job["run"], "ok": reason == "success", "reason": reason, "hint": hint,
            "messages": messages,
            "meta": {"run": job["run"], "game": job["game"], "ok": reason == "success", "reason": reason,
                     "detail": detail, "sec": round(time.time() - t0, 1), "model_calls": len(llm.calls),
                     "env_steps": len(ep._sent), "max_prompt_tokens": max(prompt_tokens, default=0),
                     "completion_tokens": sum(c["completion_tokens"] or 0 for c in llm.calls),
                     "append_only": append_only, "calls": llm.calls}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default=str(ROOT / "view"))
    ap.add_argument("--split", default="train", choices=["train", "val", "test"])
    ap.add_argument("--allow-test", action="store_true", help="test split is for the final measurement only")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--games", nargs="*", help="explicit game files (relative to data root)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--hint-level", type=int, default=0, help="0: ok/reason only; 1: + expert steps; 2: + plan")
    ap.add_argument("--url", default="http://127.0.0.1:8089/v1")
    ap.add_argument("--model", default="ornith15-9b")
    ap.add_argument("--wall-limit", type=int, default=3600, help="seconds per episode")
    ap.add_argument("--fake", help="JSON script for the stub model (no LLM calls)")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--no-publish", action="store_true", help="do not replace <view>/logs")
    a = ap.parse_args()

    if a.split == "test" and not a.allow_test:
        sys.exit("test split is reserved for the final measurement (use --allow-test)")
    view, out = Path(a.view).resolve(), ROOT / "runs" / a.tag
    if out.exists():
        sys.exit(f"{out} exists")
    src = view / "src"
    splits = json.loads((ROOT / "splits.json").read_text())
    games = a.games or random.Random(a.seed).sample(splits[a.split], a.n)
    stand = {"worker_env": worker_env(), "url": a.url, "model": a.model}
    if a.fake is None:
        penalties = {v.get("QWEN_PRESENCE_PENALTY") for v in stand["worker_env"].values() if isinstance(v, dict)}
        if penalties != {"0"}:
            sys.exit(f"worker presence penalty is not 0: {stand['worker_env']}")

    out.mkdir(parents=True)
    shutil.copytree(src, out / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (out / "logs").mkdir()
    info = {"tag": a.tag, "src_hash": src_hash(out / "src"), "split": a.split, "seed": a.seed, "n": len(games),
            "hint_level": a.hint_level, "fake": a.fake, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "workers": a.workers, **stand}
    (out / "run.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info), flush=True)

    jobs = [{"run": i + 1, "game": g, "src": str(out / "src"), "fake": json.loads(a.fake) if a.fake else None,
             "url": a.url, "model": a.model, "hint_level": a.hint_level, "wall_limit": a.wall_limit}
            for i, g in enumerate(games)]
    results, t0 = [], time.time()
    with cf.ProcessPoolExecutor(a.workers, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as pool:
        futs = {pool.submit(play, j): j for j in jobs}
        for f in cf.as_completed(futs):
            try:
                r = f.result()
            except Exception:
                j = futs[f]
                r = {"run": j["run"], "ok": False, "reason": "runner error", "hint": None, "messages": [],
                     "meta": {"run": j["run"], "game": j["game"], "detail": traceback.format_exc()}}
            results.append(r)
            with open(out / "logs" / f"run_{r['run']}.jsonl", "w") as fh:
                for m in r["messages"]:
                    fh.write(json.dumps(m, ensure_ascii=False) + "\n")
            with open(out / "meta.jsonl", "a") as fh:
                fh.write(json.dumps(r["meta"], ensure_ascii=False) + "\n")
            m = r["meta"]
            print(f"[{time.time() - t0:7.0f}s] run {r['run']:3d} ok={r['ok']!s:5} {r['reason']:<18} "
                  f"calls={m.get('model_calls')} ctx={m.get('max_prompt_tokens')} sec={m.get('sec')}", flush=True)

    results.sort(key=lambda r: r["run"])
    with open(out / "logs" / "results.jsonl", "w") as fh:
        for r in results:
            row = {"run": r["run"], "ok": r["ok"], "reason": r["reason"]}
            if a.hint_level > 0:
                row["hint"] = r["hint"]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    ok = sum(r["ok"] for r in results)
    summary = {"ok": ok, "n": len(results), "wall_sec": round(time.time() - t0, 1)}
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
