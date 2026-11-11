"""Рабочий каталог сессии: work/<tag>/ = README.md, src/ и logs/ вида + tests/ (smoke, rerun, runs); профиль песочницы,
хэш дерева, diff копии с видом."""
import glob
import hashlib
import os
import re
import shutil
import subprocess

from .cfg import F
from . import cfg as C

SMOKE_README = ("- `tests/smoke.py` — a smoke test: runs src/harness.py with a stub benchmark and a stub model (not the "
                "benchmark) and prints what the harness adds to the conversation after which model reply, or the error. "
                "Run it with `python3 tests/smoke.py`.\n")


RERUN_README = """- `tests/rerun.py` — replays the runs recorded in `logs/` on the current `src/`. The model's replies and the task's messages are taken from the log, so neither the model nor the benchmark is called. As long as what the harness gives the model and the task is the same as in the log, the log still describes the run; at the first place where it differs, the replay of that run stops: from that point on the rest of the log no longer applies, and what the model would do next is not known. `python3 tests/rerun.py` says for each run what the harness did at that place in the log and what it does now, the passed runs first; "goes exactly as in the log" (or `no changes`) means that in those runs the current `src/` gives the model and the task exactly what the log has. `python3 tests/rerun.py N` shows run N in detail, with the line of `logs/run_N.jsonl`: `-` what the log has there, `+` what the harness does now, and the hooks whose answer changed compared with `src/` as it was at the start (a copy of it is in `tests/orig_src/`). An example, from the harness of another agent, where a hook was added that says "foobar" when the observation has both "foo" and "bar" in it:
```
$ python3 tests/rerun.py
9 runs replayed on your src/. 6 go differently from the log: 2 passed runs and 4 failed runs. 3 go exactly as in the log. Each run is replayed up to the first place where the harness does something different from the log; what the model would do after that is not known: the replay only has the model's replies from the log.

Passed runs (in the log the task was solved). 2 of them now go differently:
- run 6, model call 12. Now the harness gives the model a message that the log does not have here: "foobar" This message comes from the hook on_observation; with the original src/ the hook returned None here.
- run 8, model call 30. The same as run 6: now the harness gives the model a message that the log does not have here.
- runs 5, 9. Go exactly as in the log.

Failed runs. 4 of them now go differently:
- run 1, model call 12. The same as run 6: now the harness gives the model a message that the log does not have here.
- run 3, model call 17. The same as run 6: now the harness gives the model a message that the log does not have here.
- run 4, model call 17. The same as run 6: now the harness gives the model a message that the log does not have here.
- run 7 (model call 30). The same as run 6.
- run 2. Goes exactly as in the log.
$ python3 tests/rerun.py 3
run 3 (failed): diverges at model call 17 (log line 52): what the model sees differs from the log
  - assistant: The foo is next to the bar, I will take the foo. | act: take foo
  + user: foobar
  hook on_observation at model call 17: {"message": "foobar"} (was None)
```
"""

READ_FAILED = "  - Read the failed runs; the passed runs are there for comparison and grep.\n"

RUNS_README = ("- `tests/runs.py` — reads the runs recorded in `logs/`. `python3 tests/runs.py steps N` prints run N in short, "
               "one line per model call: its number, the log line, what the model sent → the first line of what came "
               "back (`steps N 20-30`: calls 20-30). The call numbers are those in the output of `tests/rerun.py`. "
               "`python3 tests/runs.py show N 40-45` prints lines 40-45 of the log in full.\n")


def runs_py():
    """10.11: bin/runs (навигация по логам, инструмент исследователя) — в копию писателя как tests/runs.py."""
    from .. import plain
    src = open(os.path.join(os.path.dirname(C.SMOKE), "..", "bin", "runs")).read()
    src = plain.strip(src.split("\n", 1)[1])[0]       # без строки запуска, комментариев и докстрингов
    for cmd in ("show", "grep", "steps", "--help"):
        src = src.replace(f"runs {cmd}", f"python3 tests/runs.py {cmd}")
    return src.replace('"""runs — the run logs', '"""python3 tests/runs.py — the run logs')


RERUN_AT_README = """`python3 tests/rerun.py N --at K` replays run N on the current `src/` up to model call K and shows, for the step just before it, the lines of the log and every call of a function in `src/harness.py` and `src/hooks.py`, with the values it got and returned: the values the harness really has at that point of the run. An example, from the same other agent:
```
$ python3 tests/rerun.py 3 --at 17
run 3 (failed), before model call 17 (log line 52):
  the log just before it:
    assistant: I will look in the box. | act: open box
    tool: The box is open. In it you see a foo and a bar.
  calls of the functions in src/harness.py and src/hooks.py, with the values they got and returned:
    harness.make_ctx({'observation': 'The box is open. In it you see a foo and a bar.'}, {'actions': [... 12 more, 'go to box', 'open box']}) -> {'observation': 'The box is open. In it you see a foo and a bar.', 'step': 16, 'history': {'actions': [... 12 more, 'go to box', 'open box']}}
    harness.call_hook('on_observation', <same as above>) -> {'message': 'foobar'}
      hooks.on_observation(<same as above>) -> {'message': 'foobar'}
```
"""

RERUN_PY = """\"\"\"Replays the runs recorded in logs/ on src/; see README.md.\"\"\"
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
import rerun_core as R  # noqa: E402

logs = os.path.join(ROOT, "logs")
args = sys.argv[1:]
if "--at" in args:
    i = args.index("--at")
    try:
        at, args = int(args[i + 1]), args[:i] + args[i + 2:]
    except (IndexError, ValueError):
        sys.exit("usage: python3 tests/rerun.py N --at K  (K: the number of a model call in run N)")
    if len(args) != 1:
        sys.exit("usage: python3 tests/rerun.py N --at K  (one run N)")
    t = R.worker(BENCH, os.path.join(ROOT, "src"), logs, args, at)
    if args[0] not in t:
        sys.exit(f"no run {args[0]} in logs/")
    print(R.report_at(args[0], t[args[0]], os.path.join(logs, f"run_{args[0]}.jsonl"), at,
                      bool(R.results(logs).get(args[0], {}).get("ok"))))
    sys.exit(0)
new = R.worker(BENCH, os.path.join(ROOT, "src"), logs)
old = R.worker(BENCH, os.path.join(HERE, "orig_src"), logs)
runs = args or list(new)
missing = [r for r in runs if r not in new]
if missing:
    sys.exit(f"no run {', '.join(missing)} in logs/; the runs are {', '.join(new)}")
print(R.report(new, old, R.results(logs), runs, detail=bool(args)))
"""


WORK_MTIME = 1793491200   # 2026-11-01 00:00 UTC


def tool_run(run, name, args=""):
    """python3 tests/<name>.py (rerun | smoke) в песочнице копии -> (ok, вывод с обрезкой, вывод целиком)."""
    ok, out, full, _, _ = F.bash_output(f"python3 tests/{name}.py{args}", run.root, run.prof)
    return ok, out, full


def build_work(bench, tag):
    """Рабочая копия вида: README.md (+ описание tests/), src/, logs/, tests/ (smoke, rerun, runs, orig_src)."""
    C.BENCH = bench
    view, v = C.VIEWS[bench], f"{C.HERE}/work/{tag}"
    if os.path.lexists(v):
        shutil.rmtree(v)
    os.makedirs(f"{v}/tests")
    readme = open(f"{view}/README.md").read()
    assert readme.count(READ_FAILED) == 1   # 4.11, автор: писатель сначала доверяет коллеге (строка — для ревьювера)
    readme = readme.replace(READ_FAILED, "").rstrip("\n") + "\n"
    with open(f"{v}/README.md", "w") as f:
        f.write(readme + RERUN_README + RERUN_AT_README + RUNS_README + SMOKE_README)
    shutil.copytree(f"{view}/src", f"{v}/src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(f"{view}/src", f"{v}/tests/orig_src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(f"{view}/logs", f"{v}/logs")
    shutil.copy(f"{C.SMOKE}/{bench}.py", f"{v}/tests/smoke.py")
    # Ядро повтора одно — editor/rerun.py: в копию писателя оно идёт без комментариев и докстрингов, как src/ вида,
    # и по нему же (под тем же python3 песочницы) идёт проверка по тикету.
    from .. import plain
    core = open(os.path.join(os.path.dirname(C.SMOKE), "..", "..", "editor", "rerun.py")).read()
    for name, text in (("rerun_core.py", plain.strip(core)[0]), ("rerun.py", RERUN_PY.replace("BENCH", repr(bench))),
                       ("runs.py", runs_py())):
        with open(f"{v}/tests/{name}", "w") as f:
            f.write(text)
    for p in glob.glob(f"{v}/src/*"):
        assert os.stat(p).st_nlink == 1, p          # копия, не жёсткая ссылка
    for d, dirs, files in os.walk(v, topdown=False):    # время файлов одно на все сессии: ls -la не разводит пары
        for x in files + dirs:
            os.utime(os.path.join(d, x), (WORK_MTIME, WORK_MTIME), follow_symlinks=False)
    for x in (v, os.path.dirname(v)):                    # и «..» копии: work/ свой у каждой сессии
        os.utime(x, (WORK_MTIME, WORK_MTIME))
    return os.path.realpath(v)


def make_profile(root, tag):
    p = f"{C.HERE}/work/.sb_{tag}_{os.getpid()}.sb"
    with open(p, "w") as f:
        f.write(F.profile_text(root))
    F._PROFILES.append(p)
    os.utime(os.path.dirname(p), (WORK_MTIME, WORK_MTIME))   # 6.11: профиль пишется в work/ — «..» копии снова одно время
    return p


def tree_hash(d):
    h = hashlib.sha256()
    for p in sorted(glob.glob(f"{d}/**/*", recursive=True)):
        if os.path.isfile(p) and "__pycache__" not in p:
            h.update(os.path.relpath(p, d).encode() + b"\0" + open(p, "rb").read() + b"\0")
    return h.hexdigest()[:16]


def diff_src(bench, root):
    r = subprocess.run(["diff", "-ruN", "-x", "__pycache__", f"{C.VIEWS[bench]}/src", f"{root}/src"],
                       capture_output=True, text=True)
    out = r.stdout.replace(C.VIEWS[bench] + "/", "a/").replace(root + "/", "b/")
    return re.sub(r"(?m)^((?:---|\+\+\+) [ab]/\S+)\t.*$", r"\1", out)   # без времени файлов: одна сессия — один diff
