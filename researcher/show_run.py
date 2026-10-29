"""Компактный вид run_N.jsonl для проверки report: номер строки, роль, текст (без списка AVAILABLE ACTIONS)."""
import json, sys
p = sys.argv[1]; w = int(sys.argv[2]) if len(sys.argv) > 2 else 220
for i, l in enumerate(open(p), 1):
    m = json.loads(l)
    c = (m.get("content") or "")
    if m["role"] == "system":
        c = c[:80]
    acts = ""
    if " AVAILABLE ACTIONS: " in c:
        c, acts = c.split(" AVAILABLE ACTIONS: ", 1)
        acts = f" [{len(acts.split(chr(10)))-1} acts]"
    tc = " -> " + "; ".join(t["function"]["arguments"] for t in m.get("tool_calls") or []) if m.get("tool_calls") else ""
    c = c.replace("\n", " ")
    print(f"{i:3d} {m['role'][:4]}: {c[:w]}{acts}{tc}")
