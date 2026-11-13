"""Счёт ответов оценщика против слепой разметки: python3 probes/1112/ev_score.py ITEMS.json OUT.jsonl [OUT2 …]
ITEMS — с полем blind. Печатает: плохих поймано, ложных Failed, верных из N, место не в прогоне наблюдения, токены."""
import json
import statistics
import sys

items = {i["state"]: i for i in json.load(open(sys.argv[1]))}
for p in sys.argv[2:]:
    rows = [r for r in map(json.loads, open(p)) if r["state"] in items]
    bad = [r for r in rows if items[r["state"]]["blind"] == "Failed"]
    good = [r for r in rows if items[r["state"]]["blind"] == "Ok"]
    cb = sum(r["verdict"] == "Failed" for r in bad)
    fg = sum(r["verdict"] == "Failed" for r in good)
    none = sum(r["verdict"] is None for r in rows)
    pt = statistics.median(r["usage"]["prompt_tokens"] for r in rows)
    ct = statistics.median(r["usage"]["completion_tokens"] for r in rows)
    print(f"{p.split('/')[-1]:40} n={len(rows)} поймано {cb}/{len(bad)} ложных F {fg}/{len(good)} верно {cb + len(good) - fg}/{len(rows)}"
          f" без вердикта {none} ток.вход {pt:.0f} ток.ответ {ct:.0f} сек {statistics.median(r['sec'] for r in rows):.0f}")
