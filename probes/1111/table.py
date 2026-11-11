"""Таблица серии писателя: python3 probes/1111/table.py HOME [часть тега]
Строка на сессию: ходы, bash, ход первой правки, правок применено/всего, последний ответ проверки по тикету и keep,
чем кончилась, пик окна, минуты модели и проигрыш итогового src/ на всех прогонах вида: сколько проваленных и удачных
прогонов идут иначе, чем в логе (при изменённом промпте — код с прежним промптом, пометка «п»)."""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

H = sys.argv[1]
SUB = sys.argv[2] if len(sys.argv) > 2 else ""
PY = "/Users/user/Projects/nrhsi/nrhsi/bin/python3"


def replay(work):
    """(проваленных иначе, удачных иначе, есть ли падение) по editor/rerun.py --json; None — промпт отличается от лога."""
    bench = re.search(r"R\.worker\('(\w+)'", open(f"{work}/tests/rerun.py").read()).group(1)
    r = subprocess.run([PY, "/Users/user/Projects/nrhsi/editor/rerun.py", "--bench", bench, "--src", f"{work}/src",
                        "--logs", f"{work}/logs", "--json"], capture_output=True, text=True)
    div = json.loads(r.stdout.strip().splitlines()[-1])
    ok = {str(json.loads(l)["run"]): bool(json.loads(l).get("ok")) for l in open(f"{work}/logs/results.jsonl")}
    f = p = 0
    crash = False
    for run, d in div.items():
        if d is None:
            continue
        if d["kind"] == "model" and d["call"] == 1:
            return None
        crash |= d["kind"] == "crash"
        f, p = f + (not ok[run]), p + ok[run]
    return f, p, crash


print("сессия | ходов | bash | 1-я правка | правок | тикет / keep (последняя проверка) | конец | пик | мин | иначе: провал/удачн")
for log in sorted(glob.glob(f"{H}/logs/*{SUB}*.jsonl")):
    tag = os.path.basename(log)[:-6]
    L = [json.loads(x) for x in open(log)]
    end = [x for x in L if x.get("type") == "end"]
    if not end:
        print(f"{tag} | идёт: {sum(x.get('type') == 'turn' for x in L)} ходов")
        continue
    st, turns = end[-1]["stats"], [x for x in L if x.get("type") == "turn"]
    fe = next((x["i"] for x in turns if any(c["name"] == "edit" for c in x.get("tool_calls") or [])), None)
    last = ""
    for x in turns:
        for r in x.get("results") or []:
            s = r.get("shown") or ""
            j = s.find("Check against the observation:")
            if r.get("name") == "edit" and j >= 0:
                last = " / ".join(l.split(":")[0] for l in s[j:].splitlines()[1:3])
    work = f"{H}/work/{tag}"
    rp = replay(work) if os.path.isdir(work) else None
    mark = ""
    if rp is None and os.path.isdir(work):
        tmp = tempfile.mkdtemp()
        shutil.copytree(work, f"{tmp}/w", symlinks=True)
        for f in glob.glob(f"{tmp}/w/tests/orig_src/*.md"):
            shutil.copy(f, f"{tmp}/w/src/" + os.path.basename(f))
        rp, mark = replay(f"{tmp}/w"), " п"
        shutil.rmtree(tmp)
    rs = "?" if rp is None else f"{rp[0]}/{rp[1]}" + (" падает" if rp[2] else "") + mark
    print(f"{tag} | {st['turns']} | {st['bash_calls']} | {fe} | {st['edits_applied']}/{st['edits_attempted']} | {last or '—'} | "
          f"{end[-1]['reason'][:28]} | {st['max_prompt']} | {round(st['model_sec'] / 60, 1)} | {rs}")
