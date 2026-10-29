"""Исследователь: 9B читает src/ и логи прогонов узла и пишет report о слабостях харнесса.

  python nrhsi/researcher.py --node runs/base --readme bench/alfworld/view_readme.md --k 5 --seed 1 --out DIR

Каталог сессии (OUT/view): README.md, src/, logs/ = K случайных проваленных прогонов + все пройденные.
Итог — OUT/reports.json (принятые report), лог сессии — OUT/session.jsonl.
"""
import argparse
import json
import os
import random
import re
import shutil

import agent

SYSTEM = f"""You are a research agent working in a read-only copy of a repository: the source code of an AI agent's harness (its prompts and the code that runs it) and the logs of the agent's runs on tasks. Some runs passed and some failed.

Your job: find the weaknesses of the harness — in its prompts or its code — that make runs fail, and show how each one leads to failure. Look for concrete problems in individual failed runs, behaviour patterns that recur across runs, and meta-observations about how the runs unfold as a whole. Name the part of the harness responsible whenever you can tell. Every finding must rest on lines you have actually read in the files.

# Tools
{agent.BASH_LINE}; read the logs with runs.
- runs (a program in bash) reads the run logs message by message:
    runs                          list runs: result, reason, size
    runs show N 40-45             messages 40-45 (= lines 40-45 of logs/run_N.jsonl)
    runs show N --tail 6          the last 6 messages
    runs grep -i "error" N M      matches in runs N and M, with message numbers
{agent.BSD_LINE}
{agent.PY_LINE}
- report(kind, observation, evidence): record one finding. kind is "problem", "pattern" or "meta". evidence is a list of what supports the finding, in free form: a short quote copied from a file together with its path, "path:line" or "path:start-end", or a path alone, for example ["logs/run_N.jsonl: <short quote>", "src/FILE:12-30"]. Paths are checked to exist; line numbers and quotes are not checked.
- finish(): end the investigation.

# How to work
- README.md describes the layout.
- Work like an engineer debugging a system: look around, form a hypothesis, check it against the files, record it, continue.
- Record each finding with report as soon as you have its supporting lines. The context is not cleared, and bash can be called BASH_LIMIT times; after that only report and finish remain, for a few turns, and the session ends. Recorded findings are kept.
- Targeted commands (grep -n, sed -n ranges, runs show N A-B) work better than printing many whole files at once.
- An example of how a session can start:
    bash: cat README.md
    >> (the layout)
    bash: cat -n src/harness.py
    >> (the code)
    ... the prompts and other files you need
    bash: runs
    >> (runs with their results)
    bash: runs show N 1-2
    >> (the first messages, trimmed) -- the prompt from src/, as expected
    bash: runs show N --tail 6
    >> (how the run ended)
    ... then find where it went wrong, compare with a passed run, report.
- Call finish when you are done."""

FIRST_USER = ("Investigate the failed runs in this repository and report what in the harness makes them fail. "
              "Call finish when you are done.")
FINAL_MSG = "Limit reached, stop exploring. Write your findings now: one report call per finding, then finish."
BASH_LIMIT = 40

REPORT_TOOL = {"type": "function", "function": {
    "name": "report", "description": "Record one finding with evidence. Call it as soon as a finding is supported; "
    "several report calls in one reply are fine.",
    "parameters": {"type": "object", "properties": {
        "kind": {"type": "string", "enum": ["problem", "pattern", "meta"]},
        "observation": {"type": "string", "description": "What you found and why it matters"},
        "evidence": {"type": "array", "items": {"type": "string"},
                     "description": "What supports the finding, in free form: a short quote with the path of its file "
                                    "(e.g. logs/run_N.jsonl: <short quote>), 'path:line', 'path:start-end' or a path; "
                                    "paths are checked to exist"}},
        "required": ["kind", "observation", "evidence"]}}}
REPORT_EXAMPLE = 'report(kind="pattern", observation="...", evidence=["logs/run_N.jsonl: <short quote>", "src/FILE:12-30"])'
PATH_HEAD = re.compile(r"^\s*(?:\./)?([^\s:]+)(?::|\s*$)")


def build_view(node, readme, k, seed, view):
    rows = [json.loads(x) for x in open(f"{node}/logs/results.jsonl") if x.strip()]
    failed = [r["run"] for r in rows if not r["ok"]]
    pick = set(random.Random(seed).sample(failed, min(k, len(failed))))
    rows = [r for r in rows if r["ok"] or r["run"] in pick]
    shutil.copytree(f"{node}/src", f"{view}/src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(readme, f"{view}/README.md")
    os.makedirs(f"{view}/logs")
    for r in rows:
        shutil.copy(f"{node}/logs/run_{r['run']}.jsonl", f"{view}/logs/")
    with open(f"{view}/logs/results.jsonl", "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    return sorted(pick)


def check_report(args, root):
    errs = []
    if args.get("kind") not in ("problem", "pattern", "meta"):
        errs.append("kind must be one of problem, pattern, meta")
    if not str(args.get("observation") or "").strip():
        errs.append("observation must be a non-empty string")
    ev = args.get("evidence")
    ev = [ev] if isinstance(ev, str) else ev if isinstance(ev, list) else []
    ev = [str(x) for x in ev if str(x).strip()]
    if not ev:
        errs.append("evidence must be a non-empty list of strings")
    for e in ev:
        m = PATH_HEAD.match(e)
        path = m.group(1) if m else None
        if path and re.search(r"/|\.[A-Za-z]{1,6}$", path.rstrip("/")):
            full = os.path.realpath(os.path.join(root, path))
            if not full.startswith(root + "/") or not os.path.exists(full):
                errs.append(f"{e[:200]!r}: no such file or directory '{path}'")
    return errs, ev


def run(node, readme, k, seed, out):
    view = os.path.realpath(f"{out}/view")
    os.makedirs(out)
    picked = build_view(node, readme, k, seed, view)
    reports = []

    def handle(name, args):
        errs, ev = check_report(args, view)
        if errs:
            return ("Error: report not recorded.\n- " + "\n- ".join(errs) + "\nEach evidence item is free-form text: "
                    "a short quote with the path of its file, 'path:line', 'path:start-end' or a path; a path in it "
                    "must exist in the directory. Fix it and call report again, e.g. " + REPORT_EXAMPLE), False
        reports.append({"kind": args["kind"], "observation": args["observation"], "evidence": ev})
        return f"Recorded finding #{len(reports)}.", True

    end = agent.session(SYSTEM.replace("BASH_LIMIT", str(BASH_LIMIT)), FIRST_USER, [REPORT_TOOL], handle, view,
                        f"{out}/session.jsonl", BASH_LIMIT, FINAL_MSG, seed)
    json.dump({"runs": picked, "end": end, "reports": reports}, open(f"{out}/reports.json", "w"),
              ensure_ascii=False, indent=1)
    return reports


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True, help="каталог замера: src/ и logs/ (bench/run.py --out)")
    ap.add_argument("--readme", required=True, help="README.md каталога для модели (bench/*/view_readme.md)")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(json.dumps(run(a.node, a.readme, a.k, a.seed, a.out), ensure_ascii=False, indent=1))
