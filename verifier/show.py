"""Транскрипт сессии проверяльщика: python3 show.py R03 [символов вывода]"""
import json, sys
n = int(sys.argv[2]) if len(sys.argv) > 2 else 700
for l in open(f"logs/{sys.argv[1]}.jsonl"):
    r = json.loads(l)
    if r["type"] == "turn":
        print(f"--- turn {r['i']} {r['sec']}s prompt={r.get('usage', {}).get('prompt_tokens')} final={r['final']}")
        if r.get("content"):
            print("TEXT:", r["content"][:n])
        for x in r["results"]:
            print("CALL", x["name"], x.get("command") or "", "\n  ->", x["shown"][:n].replace("\n", "\n     "))
    elif r["type"] == "end":
        print("END", r["reason"], json.dumps(r["result"], ensure_ascii=False)[:2500], r["stats"])
    elif r["type"] != "meta":
        print(r)
