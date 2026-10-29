"""Сводка R2: python3 table.py [results.jsonl] — таблица по report и метрики (последняя запись на id)."""
import csv
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
res_p = sys.argv[1] if len(sys.argv) > 1 else f"{HERE}/results.jsonl"
rows = {r["id"]: r for r in csv.DictReader(open(f"{HERE}/set.tsv"), delimiter="\t")}
res = {}
for l in open(res_p):
    x = json.loads(l)
    res[x["id"]] = x

print("| id | бенч | сессия | утверждение | метка | посылка | вердикт | bash | пик prompt | мин |")
print("|---|---|---|---|---|---|---|---|---|---|")
for rid, r in rows.items():
    x = res.get(rid)
    if not x:
        continue
    print(f"| {rid} | {r['bench']} | {r['tag']} #{r['n']} | {r['claim_short']} | {r['label']} | {r['premise']} | "
          f"{x['verdict']} | {x['bash_calls']} | {x['max_prompt']/1000:.1f}K | {x['model_sec']/60:.1f} |")


def dist(ids):
    c = {}
    for i in ids:
        v = res[i]["verdict"]
        c[v] = c.get(v, 0) + 1
    return c


def line(name, ids):
    if not ids:
        return
    c = dist(ids)
    n = len(ids)
    print(f"- {name}: n={n}; " + ", ".join(f"{k} {v} ({v/n:.0%})" for k, v in sorted(c.items())))


done = [i for i in rows if i in res]
print()
for bench in (None, "app", "alf"):
    sel = [i for i in done if bench in (None, rows[i]["bench"])]
    tag = bench or "все"
    line(f"{tag}: ложные", [i for i in sel if rows[i]["label"] == "false"])
    line(f"{tag}: верные", [i for i in sel if rows[i]["label"] == "true"])
line("демо-посылка (ложные)", [i for i in done if rows[i]["premise"] == "demo"])
line("won-посылка (ложные)", [i for i in done if rows[i]["premise"] == "won"])
line("ложные без этих посылок", [i for i in done if rows[i]["label"] == "false" and rows[i]["premise"] == "-"])
line("демо распознано верно (R08)", [i for i in done if rows[i]["premise"] == "demo-true"])
mins = [res[i]["model_sec"] / 60 for i in done]
peaks = [res[i]["max_prompt"] for i in done]
bash = [res[i]["bash_calls"] for i in done]
if mins:
    print(f"\nмин модели на report: сред. {statistics.mean(mins):.1f}, медиана {statistics.median(mins):.1f}, "
          f"мин {min(mins):.1f}, макс {max(mins):.1f}, сумма {sum(mins):.0f}")
    print(f"пик prompt: медиана {statistics.median(peaks)/1000:.1f}K, макс {max(peaks)/1000:.1f}K")
    print(f"bash на сессию: медиана {statistics.median(bash)}, концы: " +
          ", ".join(f"{k} {v}" for k, v in sorted({e: sum(res[i]['end'] == e for i in done)
                                                   for e in {res[i]['end'] for i in done}}.items())))
