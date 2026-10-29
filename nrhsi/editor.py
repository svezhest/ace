"""Редактор: 9B правит копию src/ по наблюдениям исследователя (трасс не видит), инструмент edit(path, old, new).

  python nrhsi/editor.py --src runs/base/src --readme bench/alfworld/view_readme.md --reports R/reports.json --out DIR

Итог — OUT/work/src (правленая копия), OUT/edits.json, лог сессии OUT/session.jsonl.
"""
import argparse
import json
import os
import shutil

import agent

SYSTEM = f"""You are working in a copy of a repository that holds the harness of an AI agent: the prompts and the code that run the agent on tasks. README.md describes the layout; the harness is in src/. This directory is everything there is to read: the agent's runs and the benchmark are not here, and the harness cannot be run.

The agent's failed runs were studied by a colleague; their observations are in the first message. The runs themselves are not in this copy.

Your goal: change src/ so that the agent fails fewer tasks. Each observation that points to a weakness of the harness is a candidate for a change. An observation may also be inaccurate, or point to something the harness cannot change; what it says about src/ you can check by reading src/. The same harness runs on every task the agent gets, so aim for changes that help on tasks in general. A change may be to a prompt or to the code.

# Tools
{agent.BASH_LINE}.
{agent.BSD_LINE}
- edit(path, old_string, new_string): replace old_string with new_string in the file at path, a file in src/ (src/bridge.py is not part of the harness, see README.md). old_string must be copied exactly from the file as it is now, spaces and line breaks included, and occur in it exactly once; include enough of the neighbouring lines to make it unique. To add text, put an existing neighbouring line in old_string and repeat it in new_string together with the addition. To write into an empty file or to create a new file in src/, give an empty old_string. Each edit is applied at once and you see the changed lines; an edit that cannot be applied leaves the file as it was and tells you why.
- finish(): end the session when your changes are done.

# How to work
- Read the part of src/ a change touches before you edit it, and keep intact what the rest of the harness relies on: README.md and the comments at the top of the code describe how the parts fit together.
- Since the harness cannot be run, check each change by reading the changed lines together with the code that calls or uses them.
- bash can be called BASH_LIMIT times; after that only edit and finish remain, for a few turns, and the session ends.
- Call finish when you are done."""

FINAL_MSG = "Limit reached, stop exploring. Make the edits you have settled on now (several edit calls in one reply are fine), then finish."
BASH_LIMIT = 25

EDIT_TOOL = {"type": "function", "function": {
    "name": "edit", "description": "Replace old_string with new_string in a file in src/. old_string must match the "
    "file's current text exactly (spaces, line breaks) and occur in it exactly once; an empty old_string writes into "
    "an empty file or creates a new one.",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "The file to change, e.g. src/FILE"},
        "old_string": {"type": "string", "description": "Exact text from the file to replace"},
        "new_string": {"type": "string", "description": "The text to put in its place"}},
        "required": ["path", "old_string", "new_string"]}}}


def first_user(reports):
    parts = ["Observations from a study of the agent's failed runs (references to logs/ point to the runs, which are "
             "not in this copy):"]
    for i, r in enumerate(reports, 1):
        ev = "\n".join(f"- {x}" for x in r["evidence"]) or "- (none)"
        parts.append(f"## Observation {i} ({r['kind']})\n{r['observation']}\nEvidence:\n{ev}")
    return "\n\n".join(parts) + "\n\nChange src/ so that the agent fails fewer tasks. Call finish when you are done."


def readme_without_logs(text):
    return text.split("- `logs/`")[0].rstrip("\n") + "\n"


def do_edit(args, root):
    """-> (текст для модели, применена ли правка). Пишет только в root/src, кроме bridge.py."""
    path, old, new = args.get("path"), args.get("old_string"), args.get("new_string")
    if not all(isinstance(x, str) for x in (path, old, new)):
        return "Error: edit not applied. path, old_string and new_string must all be strings.", False
    rel = os.path.normpath(os.path.relpath(path.strip(), root) if path.strip().startswith(root + "/") else path.strip())
    full = os.path.realpath(os.path.join(root, rel))
    src = os.path.join(root, "src")
    if not full.startswith(src + os.sep) or "__pycache__" in rel:
        return f"Error: edit not applied. {path} is not a file in src/; only files in src/ can be changed.", False
    if os.path.relpath(full, src) == "bridge.py":
        return ("Error: edit not applied. src/bridge.py is the connection to the benchmark, not part of the harness "
                "(README.md); it cannot be changed."), False
    if os.path.isdir(full):
        return f"Error: edit not applied. {rel} is a directory.", False
    exists = os.path.isfile(full)
    text = open(full, encoding="utf-8").read() if exists else ""
    if old == new:
        return "Error: edit not applied. old_string and new_string are the same, so there is nothing to change.", False
    if old == "":
        if text:
            return f"Error: edit not applied. old_string is empty, but {rel} is not empty; copy the text to replace from it.", False
        if not os.path.isdir(os.path.dirname(full)):
            return f"Error: edit not applied. The directory of {rel} does not exist.", False
        newtext, at = new, 0
    else:
        n = text.count(old)
        if not exists or n == 0:
            return (f"Error: edit not applied. old_string does not occur in {rel}; it must be copied exactly from the "
                    "file's current text."), False
        if n > 1:
            return (f"Error: edit not applied. old_string occurs {n} times in {rel}; include more of the neighbouring "
                    "text so that it occurs once."), False
        i = text.find(old)
        newtext, at = text[:i] + new + text[i + len(old):], text.count("\n", 0, i)
    if rel.endswith(".py"):
        try:
            compile(newtext, rel, "exec")
        except SyntaxError as e:
            return (f"Error: edit not applied. With this change {rel} would not parse as Python (SyntaxError: {e.msg}, "
                    f"line {e.lineno}); the file is unchanged."), False
    with open(full, "w", encoding="utf-8") as f:
        f.write(newtext)
    lines = newtext.splitlines()
    lo, hi = max(0, at - 2), min(len(lines), at + new.count("\n") + 3)
    shown = "\n".join(f"{j + 1:>6}\t{lines[j]}" for j in range(lo, min(hi, lo + 80)))
    return f"Applied: {rel}. Lines {lo + 1}-{hi} now read:\n{shown}", True


def run(src, readme, reports, out, seed=1):
    work = os.path.realpath(f"{out}/work")
    os.makedirs(work)
    shutil.copytree(src, f"{work}/src", ignore=shutil.ignore_patterns("__pycache__"))
    with open(f"{work}/README.md", "w") as f:
        f.write(readme_without_logs(open(readme).read()))
    edits = []

    def handle(name, args):
        text, ok = do_edit(args, work)
        edits.append({"path": args.get("path"), "old": args.get("old_string"), "new": args.get("new_string"), "applied": ok})
        return text, ok

    end = agent.session(SYSTEM.replace("BASH_LIMIT", str(BASH_LIMIT)), first_user(reports), [EDIT_TOOL], handle, work,
                        f"{out}/session.jsonl", BASH_LIMIT, FINAL_MSG, seed)
    json.dump({"end": end, "edits": edits}, open(f"{out}/edits.json", "w"), ensure_ascii=False, indent=1)
    return f"{work}/src", sum(e["applied"] for e in edits)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--readme", required=True)
    ap.add_argument("--reports", required=True, help="reports.json исследователя")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(run(a.src, a.readme, json.load(open(a.reports))["reports"], a.out, a.seed))
