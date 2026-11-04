"""Рабочий каталог сессии: work/<tag>/ = README.md вида без logs/ + копия src/ (+ tests/smoke.py); профиль песочницы,
хэш дерева, diff копии с видом."""
import glob
import hashlib
import os
import shutil
import subprocess

from .cfg import F
from . import cfg as C

SMOKE_README = ("- `tests/smoke.py` — a smoke test: runs src/harness.py with a stub benchmark and a stub model (not the "
                "benchmark) and prints what the harness adds to the conversation after which model reply, or the error. "
                "Run it with `python3 tests/smoke.py`.\n")


RERUN_README = """- `tests/rerun.py` — replays the runs recorded in `logs/` on the current `src/`. The model's replies and the task's messages are taken from the log, so neither the model nor the benchmark is called. As long as what the harness gives the model and the task is the same as in the log, the log still describes the run; at the first place where it differs, the replay of that run stops and the difference is printed: `-` what the log has there, `+` what the harness does now. From that point on the rest of the log no longer applies. It also shows the hooks whose answer changed compared with `src/` as it was at the start (a copy of it is in `tests/orig_src/`). `no changes` means that in those runs the current `src/` gives the model and the task exactly what the log has. `python3 tests/rerun.py` prints one line per group of runs that behave the same way; `python3 tests/rerun.py N` shows run N in detail, with the line of `logs/run_N.jsonl`. An example, from the harness of another agent, where a hook was added that says "foobar" when the observation has both "foo" and "bar" in it:
```
$ python3 tests/rerun.py
runs 2, 5, 9 (1 failed, 2 passed): no changes (same as the log to the end)
runs 1, 3, 4, 6, 7, 8 (4 failed, 2 passed): diverges at model call (12, 17, 30): what the model sees differs from the log (e.g. run 1)
  + user: foobar
  hook on_observation: {"message": "foobar"} (was None)
$ python3 tests/rerun.py 3
run 3 (failed): diverges at model call 17 (log line 52): what the model sees differs from the log
  - assistant: The foo is next to the bar, I will take the foo. | act: take foo
  + user: foobar
  hook on_observation at model call 17: {"message": "foobar"} (was None)
```
"""

READ_FAILED = "  - Read the failed runs; the passed runs are there for comparison and grep.\n"

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


SMOKE_CALLS_README = (" After each scenario it lists the functions of src/harness.py and src/hooks.py that were called "
                      "and how many times, with the exceptions raised in them, also those that a caller catches; after "
                      "the first scenario also the arguments and the return value of each function's first call.")
LOOP = "    for n, (desc, Ep, script, mk) in enumerate(scenarios(), 1):\n"
TAIL = "            print(line)\n\n\nif __name__"


def smoke_calls(src):
    """--smoke-calls (3.11): в копию smoke — трассировка вызовов (smoke/calls.py), после каждого сценария."""
    assert src.count(LOOP) == 1 and src.count(TAIL) == 1
    src = src.replace(LOOP, "    import calls\n    import hooks\n    calls.install(harness, hooks)\n" + LOOP +
                      "        calls.reset()\n")
    return src.replace(TAIL, "            print(line)\n        for line in calls.lines(full=n == 1):\n            print(line)\n\n\nif __name__")


def readme_without_logs(text):
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("- `logs/`"):
            break
        out.append(line)
    return "".join(out).rstrip("\n") + "\n"


WORK_MTIME = 1793491200   # 2026-11-01 00:00 UTC


def build_work(bench, tag, smoke=True):
    C.BENCH = bench
    v = f"{C.HERE}/work/{tag}"
    if os.path.lexists(v):
        shutil.rmtree(v)
    os.makedirs(v)
    with open(f"{C.VIEWS[bench]}/README.md") as f:
        readme = f.read() if C.RERUN else readme_without_logs(f.read())
        if C.RERUN:   # 4.11, автор: писатель сначала доверяет коллеге, логи — при сомнении (строка — для ревьювера)
            assert readme.count(READ_FAILED) == 1
            readme = readme.replace(READ_FAILED, "")
        readme = readme.rstrip("\n") + "\n"
    if smoke and C.RERUN:
        readme += RERUN_README + (RERUN_AT_README if C.RERUN_AT else "")
    if smoke:
        readme += SMOKE_README if not C.SMOKE_CALLS else SMOKE_README.replace(
            "or the error. ", "or the error." + SMOKE_CALLS_README + " ")
    with open(f"{v}/README.md", "w") as f:
        f.write(readme)
    shutil.copytree(f"{C.VIEWS[bench]}/src", f"{v}/src", ignore=shutil.ignore_patterns("__pycache__"))
    if smoke:
        os.makedirs(f"{v}/tests")
        shutil.copy(f"{C.SMOKE}/{bench}.py", f"{v}/tests/smoke.py")
        if C.SMOKE_CALLS:
            with open(f"{v}/tests/smoke.py", "w") as f:
                f.write(smoke_calls(open(f"{C.SMOKE}/{bench}.py").read()))
            shutil.copy(f"{C.SMOKE}/calls.py", f"{v}/tests/calls.py")
    if smoke and C.RERUN:
        shutil.copytree(f"{C.VIEWS[bench]}/logs", f"{v}/logs")
        shutil.copytree(f"{C.VIEWS[bench]}/src", f"{v}/tests/orig_src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(os.path.dirname(C.SMOKE), "..", "..", "editor", "rerun.py"), f"{v}/tests/rerun_core.py")
        with open(f"{v}/tests/rerun.py", "w") as f:
            f.write(RERUN_PY.replace("BENCH", repr(bench)))
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
    return p


def tree_hash(d):
    h = hashlib.sha256()
    for p in sorted(glob.glob(f"{d}/**/*", recursive=True)):
        if os.path.isfile(p) and "__pycache__" not in p:
            h.update(os.path.relpath(p, d).encode() + b"\0" + open(p, "rb").read() + b"\0")
    return h.hexdigest()[:16]


def restore_src(bench, root):
    """finish(submit=false): src/ копии — снова как src/ вида."""
    shutil.rmtree(f"{root}/src")
    shutil.copytree(f"{C.VIEWS[bench]}/src", f"{root}/src", ignore=shutil.ignore_patterns("__pycache__"))


def diff_src(bench, root):
    r = subprocess.run(["diff", "-ruN", "-x", "__pycache__", f"{C.VIEWS[bench]}/src", f"{root}/src"],
                       capture_output=True, text=True)
    return r.stdout.replace(C.VIEWS[bench] + "/", "a/").replace(root + "/", "b/")
