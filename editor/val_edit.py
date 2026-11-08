"""Замер правки на val: живьём идут только задачи, где повтор логов базы расходится с записью.

  python3 editor/val_edit.py run --bench alf --name 07_PL_s1 --view VIEW --base runs/val_1102/tree_alf_1101_n0 [--control 5]
  python3 editor/val_edit.py table

Исполнитель при T=0 детерминирован: если на записанном прогоне базы новый src даёт модели и задаче то же самое,
прогон и итог те же. --control K: ещё K незадетых задач живьём, сверка с базой по ok, числу вызовов и токенам.
Выход: runs/val_1109/NAME/ (прогон раннера), NAME.plan.json (задетые задачи и их итог в базе).
"""
import argparse
import glob
import json
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = f"{ROOT}/runs/val_1109"
BENCH = {"alf": "alfworld", "app": "appworld"}


def meta(run_dir):
    """Законченные прогоны: номер (строкой) -> строка meta.jsonl."""
    out = {}
    if os.path.exists(f"{run_dir}/meta.jsonl"):
        for line in open(f"{run_dir}/meta.jsonl"):
            m = json.loads(line)
            out[str(m["run"])] = m
    return out


def task_of(m):
    return m.get("game") or m["task"]


def run(a):
    py = f"{ROOT}/{BENCH[a.bench]}/.venv/bin/python"
    base, view = os.path.abspath(a.base), os.path.abspath(a.view)
    p = subprocess.run([py, f"{ROOT}/editor/rerun.py", "--bench", a.bench, "--src", f"{view}/src",
                        "--logs", f"{base}/logs", "--json"], capture_output=True, text=True, check=True)
    div = json.loads(p.stdout.strip().splitlines()[-1])
    done = meta(base)
    touched = [r for r in done if div.get(r)]
    rest = sorted(r for r in done if r in div and not div[r])
    control = random.Random(a.name).sample(rest, min(a.control, len(rest)))
    plan = {"bench": a.bench, "view": view, "base": base, "n_base": len(done), "base_ok": sum(m["ok"] for m in done.values()),
            "touched": [{"run": r, "task": task_of(done[r]), "ok": done[r]["ok"], "reason": done[r]["reason"],
                         "call": div[r]["call"], "text": div[r]["text"][:120]} for r in touched],
            "control": [{"run": r, "task": task_of(done[r]), "ok": done[r]["ok"], "model_calls": done[r]["model_calls"],
                         "completion_tokens": done[r]["completion_tokens"]} for r in control]}
    os.makedirs(OUT, exist_ok=True)
    json.dump(plan, open(f"{OUT}/{a.name}.plan.json", "w"), indent=1)
    tasks = [t["task"] for t in plan["touched"] + plan["control"]]
    print(f"{a.name}: touched {len(touched)} of {len(done)}, control {len(control)}", flush=True)
    if not tasks:
        return
    out = f"{OUT}/{a.name}"
    subprocess.run(["rm", "-rf", out], check=True)
    subprocess.run([py, f"{ROOT}/{BENCH[a.bench]}/runner/run.py", "--view", view, "--out", out, "--tag", f"val_{a.name}",
                    "--split", "val", "--workers", str(a.workers), "--stand", "default", "--no-publish",
                    "--games" if a.bench == "alf" else "--tasks", *tasks], check=True)


def table(_):
    print("| правка | база | задето | из них ok в базе | сделано | ok теперь | + | − | чисто | итог/база | контроль |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for path in sorted(glob.glob(f"{OUT}/*.plan.json")):
        name = os.path.basename(path)[:-len(".plan.json")]
        plan = json.load(open(path))
        by_task = {task_of(m): m for m in meta(f"{OUT}/{name}").values()}
        tr = [t for t in plan["touched"] if t["task"] in by_task]
        plus = sum(by_task[t["task"]]["ok"] and not t["ok"] for t in tr)
        minus = sum(t["ok"] and not by_task[t["task"]]["ok"] for t in tr)
        cr = [c for c in plan["control"] if c["task"] in by_task]
        same = sum(all(by_task[c["task"]][k] == c[k] for k in ("ok", "model_calls", "completion_tokens")) for c in cr)
        whole = plan["base_ok"] + plus - minus
        print(f"| {name} | {os.path.basename(plan['base'])} | {len(plan['touched'])} | {sum(t['ok'] for t in plan['touched'])} "
              f"| {len(tr)} | {sum(by_task[t['task']]['ok'] for t in tr)} | {plus} | {minus} | {plus - minus:+d} "
              f"| {whole}/{plan['n_base']} (база {plan['base_ok']}) | {same}/{len(cr)} |")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--bench", choices=sorted(BENCH), required=True)
    r.add_argument("--name", required=True)
    r.add_argument("--view", required=True)
    r.add_argument("--base", required=True, help="прогон базы на val: logs/, meta.jsonl")
    r.add_argument("--control", type=int, default=0)
    r.add_argument("--workers", type=int, default=2)
    r.set_defaults(fn=run)
    sub.add_parser("table").set_defaults(fn=table)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
