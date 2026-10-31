"""Замер харнесса: прогоны src/ на случайных задачах бенчмарка.

  python bench/run.py alfworld --src bench/alfworld/src --out runs/base --split train --n 40 --seed 1

Пишет в OUT: src/ (копия, из неё и идут прогоны), logs/run_N.jsonl (беседа эпизода, одно сообщение на строку),
logs/results.jsonl ({run, ok, reason}), meta.jsonl (служебное, исследователю не показывается), summary.json.
"""
import argparse
import concurrent.futures as cf
import importlib
import json
import multiprocessing as mp
import random
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent


def play(job):
    sys.dont_write_bytecode = True
    sys.path[:0] = [job["src"], str(HERE / job["bench"])]
    return importlib.import_module("play").play(job)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bench", choices=["alfworld", "appworld"])
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", default="train", choices=["train", "val", "test"])
    ap.add_argument("--allow-test", action="store_true", help="test — только для финального замера")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--hint-level", type=int, default=0, help="фидбек бенчмарка в results.jsonl (абляция A8)")
    ap.add_argument("--url", help="по умолчанию — шлюз :8090 (без thinking, без прокси)")
    ap.add_argument("--model", default="ornith15-9b")
    ap.add_argument("--wall-limit", type=int, default=3600, help="секунд на эпизод")
    a = ap.parse_args()

    splits = json.loads((HERE / a.bench / "splits.json").read_text())
    if a.split == "test" and not a.allow_test:
        sys.exit("test is reserved for the final measurement (--allow-test)")
    if a.split not in splits:
        sys.exit(f"{a.bench} has no {a.split} split")
    a.url = a.url or "http://127.0.0.1:8090/v1"
    tasks = a.tasks or random.Random(a.seed).sample(splits[a.split], a.n)
    out = Path(a.out).resolve()
    if out.exists():
        sys.exit(f"{out} exists")
    shutil.copytree(a.src, out / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (out / "logs").mkdir()
    (out / "run.json").write_text(json.dumps({**vars(a), "tasks": tasks}, indent=1))

    jobs = [{"bench": a.bench, "run": i + 1, "task": t, "src": str(out / "src"), "out": str(out), "url": a.url,
             "model": a.model, "wall_limit": a.wall_limit, "hint_level": a.hint_level} for i, t in enumerate(tasks)]
    results, t0 = [], time.time()
    with cf.ProcessPoolExecutor(a.workers, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as pool:
        futs = {pool.submit(play, j): j for j in jobs}
        for f in cf.as_completed(futs):
            j = futs[f]
            try:
                r = f.result()
            except Exception:
                r = {"run": j["run"], "ok": False, "reason": "runner error", "hint": None, "messages": [],
                     "meta": {"detail": traceback.format_exc()}}
            r["meta"].update(run=j["run"], task=j["task"], ok=r["ok"], reason=r["reason"])
            results.append(r)
            with open(out / "logs" / f"run_{r['run']}.jsonl", "w") as fh:
                for m in r["messages"]:
                    fh.write(json.dumps(m, ensure_ascii=False) + "\n")
            with open(out / "meta.jsonl", "a") as fh:
                fh.write(json.dumps(r["meta"], ensure_ascii=False) + "\n")
            print(f"[{time.time() - t0:6.0f}s] run {r['run']:3d} ok={r['ok']!s:5} {r['reason']}", flush=True)

    results.sort(key=lambda r: r["run"])
    with open(out / "logs" / "results.jsonl", "w") as fh:
        for r in results:
            row = {"run": r["run"], "ok": r["ok"], "reason": r["reason"]}
            if a.hint_level > 0:
                row["hint"] = r["hint"]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {"ok": sum(r["ok"] for r in results), "n": len(results), "wall_sec": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps(summary))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
