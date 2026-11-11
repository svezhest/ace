"""Сессия писателя по ходам, для чтения глазами: python3 probes/1111/read.py LOG [знаков рассуждения=500] [с хода=1]
На ход: секунды, токены, длина рассуждения; начало и конец рассуждения; текст; вызовы; у правки — new_string и ответ проверок."""
import json
import sys

LOG = sys.argv[1]
RN = int(sys.argv[2]) if len(sys.argv) > 2 else 500
FROM = int(sys.argv[3]) if len(sys.argv) > 3 else 1
one = lambda s, n: s[:n].replace("\n", " ⏎ ")
for x in (json.loads(l) for l in open(LOG)):
    if x.get("type") == "end":
        print("=== конец:", x["reason"], "|", {k: x["stats"][k] for k in ("turns", "bash_calls", "edits_applied", "edits_attempted", "max_prompt", "model_sec")})
    if x.get("type") != "turn" or x["i"] < FROM:
        continue
    u, r = x.get("usage") or {}, x.get("reasoning") or ""
    print(f"--- {x['i']} | {x.get('sec')} c | prompt {u.get('prompt_tokens')} gen {u.get('completion_tokens')} | рассужд. {len(r)} зн.")
    if r:
        print("  R:", one(r, RN) + (" … " + one(r[-RN:], RN) if len(r) > 2 * RN else one(r[RN:], RN)))
    if x.get("content"):
        print("  T:", one(x["content"], 400))
    for c, res in zip(x["tool_calls"], x.get("results") or []):
        try:
            a = json.loads(c["arguments"])
        except Exception:  # noqa: BLE001
            a = {"raw": c["arguments"][:200]}
        s = res.get("shown") or ""
        if c["name"] == "bash":
            print("  BASH:", one(a.get("command", ""), 240))
        elif c["name"] == "edit":
            print("  EDIT", a.get("path"), "| old:", one(a.get("old_string", ""), 120), "\n   new:", one(a.get("new_string", ""), 1100))
            k = s.find("Checks run")
            print("   →", one(s[k if k >= 0 else 0:], 1000))
        else:
            print(" ", c["name"], one(s, 100))
