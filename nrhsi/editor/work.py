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


def readme_without_logs(text):
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("- `logs/`"):
            break
        out.append(line)
    return "".join(out).rstrip("\n") + "\n"


def build_work(bench, tag, smoke=True):
    C.BENCH = bench
    v = f"{C.HERE}/work/{tag}"
    if os.path.lexists(v):
        shutil.rmtree(v)
    os.makedirs(v)
    with open(f"{C.VIEWS[bench]}/README.md") as f:
        readme = readme_without_logs(f.read())
    if smoke:
        readme += SMOKE_README
    with open(f"{v}/README.md", "w") as f:
        f.write(readme)
    shutil.copytree(f"{C.VIEWS[bench]}/src", f"{v}/src", ignore=shutil.ignore_patterns("__pycache__"))
    if smoke:
        os.makedirs(f"{v}/tests")
        shutil.copy(f"{C.SMOKE}/{bench}.py", f"{v}/tests/smoke.py")
    for p in glob.glob(f"{v}/src/*"):
        assert os.stat(p).st_nlink == 1, p          # копия, не жёсткая ссылка
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


def diff_src(bench, root):
    r = subprocess.run(["diff", "-ruN", "-x", "__pycache__", f"{C.VIEWS[bench]}/src", f"{root}/src"],
                       capture_output=True, text=True)
    return r.stdout.replace(C.VIEWS[bench] + "/", "a/").replace(root + "/", "b/")
