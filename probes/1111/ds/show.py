"""Ход сессии писателя коротко: python3 probes/1111/ds/show.py LOG [знаков рассуждения] [знаков ответа инструмента]"""
import json
import sys

L = [json.loads(x) for x in open(sys.argv[1])]
R, O = int(sys.argv[2]) if len(sys.argv) > 2 else 600, int(sys.argv[3]) if len(sys.argv) > 3 else 500
for x in L:
    if x.get("type") == "note":
        print(f"  [харнесс] {x['text'][:300]}")
    if x.get("type") != "turn":
        continue
    print(f"--- ход {x['i']}" + (" (без bash)" if x.get("final") else ""))
    if x.get("reasoning"):
        print("  РАССУЖДЕНИЕ:", x["reasoning"][:R].replace("\n", " ⏎ "))
    if (x.get("content") or "").strip():
        print("  ТЕКСТ:", x["content"][:400].replace("\n", " ⏎ "))
    for c, r in zip(x.get("tool_calls", []), x.get("results", [])):
        a = c["arguments"]
        try:
            a = json.loads(a)
        except Exception:  # noqa: BLE001
            pass
        if c["name"] == "edit" and isinstance(a, dict):
            print(f"  EDIT {a.get('path') or a.get('file')}:\n    - " + str(a.get("old_string"))[:700].replace("\n", "\n    - ")
                  + "\n    + " + str(a.get("new_string"))[:1500].replace("\n", "\n    + "))
            s = r.get("shown") or ""
            k = s.find("Checks run")
            print("  ОТВЕТ:", (s[k:] if k >= 0 else s)[:1600].replace("\n", "\n    "))
        else:
            print(f"  {c['name'].upper()}: {str(a.get('command') if isinstance(a, dict) else a)[:260]}")
            print("  →", (r.get("shown") or "")[:O].replace("\n", " ⏎ "))
e = [x for x in L if x.get("type") == "end"]
print("КОНЕЦ:", e[-1]["reason"] if e else None)
