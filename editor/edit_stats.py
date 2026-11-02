"""Простая статистика правщика по дереву: на сессию — правки, ребёнок, сломан ли он, сработали ли новые сообщения.

  python3 editor/edit_stats.py runs/tree_alf_1101 runs/tree_app_1101

«Сработало»: строка-сообщение (литерал от 20 символов с пробелом), добавленная в .py, встречается в логах замера
ребёнка. Грубо: живая правка без нового текста сюда не попадёт, а текст в мёртвой ветке — не найдётся.
"""
import collections
import json
import os
import re
import subprocess
import sys

LIT = re.compile(r'"([^"\\]{20,})"|\'([^\'\\]{20,})\'')


def added(parent, cand):
    """(новые литералы-сообщения в .py, число добавленных строк в .py, в остальных файлах)."""
    d = subprocess.run(["diff", "-ru", f"{parent}/src", f"{cand}/src"], capture_output=True, text=True).stdout
    lits, py, other, cur = [], 0, 0, ""
    for line in d.splitlines():
        if line.startswith("+++ "):
            cur = line.split()[1]
        elif line.startswith("+") and not line.startswith("+++"):
            if cur.endswith(".py"):
                py += 1
                lits += [a or b for a, b in LIT.findall(line) if " " in (a or b)]
            else:
                other += 1
    return lits, py, other


def child_info(cdir):
    res = [json.loads(x) for x in open(f"{cdir}/logs/results.jsonl")]
    reasons = collections.Counter(r.get("reason") for r in res)
    top, k = reasons.most_common(1)[0]
    broken = not any(r.get("ok") for r in res) and k >= 0.8 * len(res)   # все упали, почти все — одной причиной
    text = "".join(open(os.path.join(cdir, "logs", f)).read() for f in os.listdir(f"{cdir}/logs") if f.startswith("run_"))
    return broken, top, text


def main():
    rows = []
    for tree in sys.argv[1:]:
        nodes = json.load(open(f"{tree}/tree.json"))["nodes"]
        kids = {n.get("from"): k for k, n in nodes.items() if n.get("from")}
        for nid, node in nodes.items():
            for s in node.get("sessions", []):
                if not s.get("view"):
                    continue
                lits, py, other = added(f"{tree}/{nid}", s["view"])
                row = {"tree": os.path.basename(tree), "tag": s["tag"], "rv": s["reviewer"], "ed": s["editor"],
                       "applied": s["applied"], "py": py, "other": other, "msgs": len(lits), "child": kids.get(s["tag"])}
                if row["child"]:
                    c = nodes[row["child"]]
                    broken, top, text = child_info(f"{tree}/{row['child']}")
                    row.update(score=c["score"], delta=c["score"] - node["score"], broken=broken, top=top,
                               fired=sum(any(x[:40] in text for x in [m]) for m in lits))
                rows.append(row)
    for key in ("ed", "rv"):
        print(f"\n| {key} | сессий | с ребёнком | ребёнок лучше родителя | сломан | +строк .py | сообщений | сработало |")
        print("|---|---|---|---|---|---|---|---|")
        for v in sorted({r[key] for r in rows}):
            g = [r for r in rows if r[key] == v]
            m = [r for r in g if r["child"]]
            print(f"| {v} | {len(g)} | {len(m)} | {sum(r['delta'] > 0 for r in m)} | {sum(r['broken'] for r in m)} | "
                  f"{sum(r['py'] for r in g)} | {sum(r['msgs'] for r in m)} | {sum(r['fired'] for r in m)} |")
    print("\nсломанные:", ", ".join(f"{r['tree'][5:8]} {r['child']} ({r['top']})" for r in rows if r.get("broken")))


if __name__ == "__main__":
    main()
