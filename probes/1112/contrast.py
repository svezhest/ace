"""Раздел «Passed runs» для входа писателя по итогу прежней попытки: python3 probes/1112/contrast.py WORK [N=3]
WORK — рабочая копия прежней сессии (её src/ — прежняя правка). Берутся удачные прогоны вида, которые на этом src/
идут иначе, чем в логе (смена одного текста сообщения харнесса не в счёт), и по каждому — N вызовов перед местом
расхождения, выводом `tests/runs.py steps`. Кода прежней правки и её описания в разделе нет.
Перепрогон — из ветки feature/check-keep-passed (его --json называет событие на месте расхождения)."""
import json
import re
import subprocess
import sys

W, N = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3
RERUN = "/Users/user/Projects/nrhsi-wt/check-keep/editor/rerun.py"
bench = re.search(r"R\.worker\('(\w+)'", open(f"{W}/tests/rerun.py").read()).group(1)
r = subprocess.run([sys.executable, RERUN, "--bench", bench, "--src", f"{W}/src", "--logs", f"{W}/logs", "--json"], capture_output=True, text=True)
div = json.loads(r.stdout.strip().splitlines()[-1])
ok = {str(json.loads(l)["run"]): bool(json.loads(l).get("ok")) for l in open(f"{W}/logs/results.jsonl")}
hit = [(k, d["call"], d["kind"]) for k, d in div.items() if d and ok[k] and d["kind"] in ("model", "end") and d["call"] > 1
       and not (d.get("event") or "").startswith("reworded")]
if not hit:
    sys.exit("прежняя правка не задевает удачных прогонов")
more, hit = len(hit) - 3, hit[:3]   # как в ответе проверки: не больше трёх прогонов, об остальных — числом


def join(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


one = len(hit) == 1
rng = [(k, max(1, c - N), c - 1) for k, c, _ in hit]
ans = [f"to model call {c - 1} of run {k}" for k, c, kind in hit if kind == "model"]
end = [f"before model call {c} of run {k}" for k, c, kind in hit if kind == "end"]
did = ([f"the harness answered differently {join(ans)}"] if ans else []) + \
      ([f"the harness ended the episode {join(end)}, while in the log the run{'' if len(end) == 1 else 's'} go{'es' if len(end) == 1 else ''} on"] if end else [])
print("## Passed runs")
print(f"An earlier edit written for this observation also changed run{'' if one else 's'} {join([k for k, _, _ in hit])}, which passed"
      + (f" (and {more} more passed run{'s' if more > 1 else ''})" if more > 0 else "")
      + f": in the log {'the task was' if one else ('both' if len(hit) == 2 else 'these') + ' tasks were'} solved, and with that edit "
      + " and ".join(did) + ". What the log has there (" + join([f"`python3 tests/runs.py steps {k} {a}-{b}`" for k, a, b in rng]) + "):")
for k, a, b in rng:
    out = subprocess.run([sys.executable, "tests/runs.py", "steps", k, f"{a}-{b}"], cwd=W, capture_output=True, text=True).stdout.splitlines()
    k0 = next((i for i, l in enumerate(out) if l.startswith("calls: number @line")), 0)   # шапка файла, затем строки вызовов
    print("\n" + "\n".join(out[:1] + out[k0 + 1:]))
runs = sorted({str(x) for x in json.load(open(sys.argv[3]))["runs"]} if len(sys.argv) > 3 else [])
print(f"\nThe change should make the harness act differently in run{'s' if len(runs) > 1 else ''} {join(runs) if runs else 'N'} and leave "
      f"run{'' if one else 's'} {join([k for k, _, _ in hit])} exactly as in the log" + (" (the other passed runs as well)" if more > 0 else "") + ".")
