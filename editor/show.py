"""Сжатый транскрипт сессии редактора / шага вариантов: python show.py logs/<tag>.jsonl [--full]"""
import json
import sys

full = "--full" in sys.argv
p = [a for a in sys.argv[1:] if not a.startswith("--")][0]
cut = (lambda s, n: s) if full else (lambda s, n: s if len(s) <= n else s[:n] + f" …[{len(s)}]")
for l in open(p):
    r = json.loads(l)
    t = r.get("type")
    if t == "meta":
        print(f"# {r['role']} seed={r['seed']} limits={r['limits']}")
    elif t == "note":
        print(f"  [note] {cut(r['text'], 300)}")
    elif t == "turn":
        u = r.get("usage", {})
        print(f"T{r['i']} {r.get('sec')}s p={u.get('prompt_tokens')} g={u.get('completion_tokens')}"
              f"{' FINAL' if r.get('final') else ''}")
        if r.get("content"):
            print("  say:", cut(r["content"].strip(), 600))
        for c, res in zip(r.get("tool_calls", []), r.get("results", [])):
            try:
                a = json.loads(c["arguments"])
            except Exception:  # noqa: BLE001
                a = {"raw": c["arguments"]}
            if c["name"] == "bash":
                print(f"  $ {cut(a.get('command', ''), 300)}")
                print("    ->", cut(res.get("shown", "").replace("\n", "\n       "), 400 if not full else 10**9))
            elif c["name"] == "edit":
                print(f"  EDIT {a.get('path')}\n    OLD: {cut(repr(a.get('old_string')), 500)}\n    NEW: {cut(repr(a.get('new_string')), 1500)}")
                print("    ->", cut(res.get("shown", "").split("\n")[0], 300))
            elif c["name"] == "propose":
                print(f"  PROPOSE obs={a.get('observations')}\n    problem: {cut(a.get('problem', ''), 600)}\n    fix: {cut(a.get('fix', ''), 1200)}")
                print("    ->", res.get("shown", "")[:200])
            else:
                print(f"  {c['name']} {cut(json.dumps(a), 200)} -> {res.get('shown', '')[:200]}")
        if r.get("error"):
            print("  ERROR", r["error"])
    elif t == "end":
        print("END", r["reason"], json.dumps(r["stats"]))
    elif t == "error":
        print("HARNESS ERROR", r["traceback"][-800:])
