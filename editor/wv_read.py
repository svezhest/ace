"""Сводка сессий писателя runs/wvar_1104 (варианты W на 10 наблюдениях): процесс и rerun итогового src.

  python3 editor/wv_read.py [ИМЯ ...]      # ИМЯ = 00_W1 ...; без имён — все законченные

Процесс: конец, bash, правки, ходы с rerun/smoke/edit, был ли rerun и smoke после последней применённой правки,
сообщения харнесса писателя (цель, финал, обзор finish). Итог: rerun итогового src на виде наблюдения с --old,
и что с прогоном(ами) тикета.
"""
import glob
import json
import os
import re
import subprocess
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = f"{R}/runs/wvar_1104"
OBS = f"{R}/runs/manual_1103/v2/obs"
TICKET = {"00": ["6"], "01": ["1"], "02": ["19"], "03": ["9"], "04": ["7"], "05": ["6", "12"], "06": ["11"],
          "07": ["36"], "08": ["40"], "09": ["8"]}


def view_of(k):
    p = glob.glob(f"{OBS}/{k}_*.md")[0]
    v = re.match(r"<!-- вид: (\S+)", open(p).read()).group(1)
    return f"{R}/{v}", os.path.basename(p).split("_")[1]


def session(name):
    k = name[:2]
    log = f"{H}/{name}/logs/wv_{name}.jsonl"
    summ = f"{H}/{name}/out/wv_{name}.summary.json"
    if not os.path.exists(summ):
        return None
    recs = [json.loads(l) for l in open(log)]
    calls, notes = [], []
    for r in recs:
        if r.get("type") == "turn":
            for c, res in zip(r.get("tool_calls", []), r.get("results", [])):
                try:
                    a = json.loads(c["arguments"])
                except Exception:
                    a = {}
                if c["name"] == "bash":
                    if res.get("format_fail"):
                        continue                       # не выполнена (bash уже нет, битые аргументы)
                    cmd = a.get("command", "")
                    head = cmd.split("rerun.py")[0][-30:] if "rerun.py" in cmd else cmd.split("smoke.py")[0][-30:]
                    kind = ("bash" if "cat" in head or "sed" in head or "head" in head else
                            "rerun" if "rerun.py" in cmd else "smoke" if "smoke.py" in cmd else "bash")
                    calls.append((r["i"], kind, cmd))
                elif c["name"] == "edit":
                    calls.append((r["i"], "edit", a.get("path", ""), bool((res.get("edit") or {}).get("applied"))))
                else:
                    calls.append((r["i"], c["name"], ""))
        elif r.get("type") == "note":
            notes.append(r["text"][:90])
        elif r.get("type") == "end":
            end = r
    applied = [c for c in calls if c[1] == "edit" and len(c) > 3 and c[3]]
    last = max((c[0] for c in applied), default=None)
    after = lambda kind: last is not None and any(c[1] == kind and c[0] > last for c in calls)
    seq = " ".join(f"{c[0]}{ {'rerun': 'R', 'smoke': 'S', 'bash': 'b', 'edit': 'E' if len(c) > 3 and c[3] else 'e', 'finish': 'F'}.get(c[1], '?')}"
                   for c in calls)
    s = json.load(open(summ))
    view, bench = view_of(k)
    src = glob.glob(f"{H}/{name}/work/*/src")[0]
    rr = subprocess.run([sys.executable, f"{R}/editor/rerun.py", "--bench", bench, "--src", src, "--logs", f"{view}/logs",
                         "--old", f"{view}/src"], capture_output=True, text=True)
    out = (rr.stdout + rr.stderr).strip()
    tk = subprocess.run([sys.executable, f"{R}/editor/rerun.py", "--bench", bench, "--src", src, "--logs", f"{view}/logs",
                         *TICKET[k]], capture_output=True, text=True).stdout.strip()
    diff = open(f"{H}/{name}/out/wv_{name}.diff").read()
    files = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", diff, re.M)))
    return {"name": name, "end": s["editor"]["end"], "bash": end["stats"]["bash_calls"] if "stats" in end else "?",
            "edits": f"{s['editor']['stats']['edits_applied']}/{s['editor']['stats']['edits_attempted']}",
            "rerun_after_last_edit": after("rerun"), "smoke_after_last_edit": after("smoke"),
            "n_rerun": sum(c[1] == "rerun" for c in calls), "seq": seq, "notes": notes, "files": files,
            "diff_lines": sum(1 for l in diff.splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---")),
            "rerun": out, "ticket": tk}


def main():
    names = sys.argv[1:] or sorted(os.path.basename(p)[:-7] for p in glob.glob(f"{H}/*.ed.log"))
    for n in names:
        s = session(n)
        if s is None:
            continue
        print(f"=== {n}: {s['end']}; bash {s['bash']}, edits {s['edits']}, diff ±{s['diff_lines']} in {', '.join(s['files'])}")
        print(f"  rerun calls {s['n_rerun']}; after last applied edit: rerun {s['rerun_after_last_edit']}, smoke {s['smoke_after_last_edit']}")
        print(f"  seq: {s['seq']}")
        for t in s["notes"]:
            print(f"  note: {t}")
        print("  rerun all:\n" + "\n".join("    " + l[:260] for l in s["rerun"].splitlines()[:8]))
        print("  ticket:\n" + "\n".join("    " + l[:260] for l in s["ticket"].splitlines()[:6]))


if __name__ == "__main__":
    main()
