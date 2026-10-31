"""Виды сессии: выбор проваленных run, views/<имя> из жёстких ссылок, владение видом (lock)."""
import glob
import json
import os
import random
import shutil
import stat

from . import cfg as C


# ---------------------------------------------------------------- виды

def results_rows():
    return [json.loads(l) for l in open(f"{C.LAYOUT}/logs/results.jsonl") if l.strip()]


def all_tids():
    return [r["run"] for r in results_rows() if not r["ok"]]


def select(mode, k, seed, runs=None):
    """-> (проваленные run в виде, sel). runs — явный список; иначе k случайных проваленных с seed."""
    failed = all_tids()
    if runs:
        assert all(r in failed for r in runs), (runs, failed)
        return sorted(runs), {"explicit": True}
    rng = random.Random(seed)
    return sorted(rng.sample(failed, k)), {"rand_seed": seed}


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def claim_view(name):
    """v3c: имя вида на сессию. Владелец вида — pid в views/.<имя>.lock (вне вида). Вид живой сессии не трогаем:
    занято живым процессом -> имя с суффиксом _p<pid>. -> (имя, путь lock-файла)."""
    os.makedirs(f"{C.HERE}/views", exist_ok=True)
    for cand in (name, f"{name}_p{os.getpid()}"):
        lock = f"{C.HERE}/views/.{cand}.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                with open(lock) as f:
                    owner = int(f.read().strip() or 0)
            except (OSError, ValueError):
                owner = 0
            if owner and owner != os.getpid() and _pid_alive(owner):
                continue                                # вид живой сессии
            fd = os.open(lock, os.O_WRONLY | os.O_TRUNC)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return cand, lock
    raise RuntimeError(f"view {name} is in use")


def release_view(lock):
    try:
        with open(lock) as f:
            mine = f.read().strip() == str(os.getpid())
        if mine:
            os.unlink(lock)
    except OSError:
        pass


def build_view(name, tids):
    """Вид views/<name>: README.md, src/, logs/ = выбранные проваленные run + все пройденные; results.jsonl — их строки."""
    v = f"{C.HERE}/views/{name}"
    if os.path.lexists(v):
        shutil.rmtree(v)
    _link(f"{C.LAYOUT}/README.md", f"{v}/README.md")
    _link(f"{C.LAYOUT}/src", f"{v}/src")
    for p in glob.glob(f"{v}/src/**/__pycache__", recursive=True):
        shutil.rmtree(p)
    rows = [r for r in results_rows() if r["ok"] or r["run"] in tids]
    os.makedirs(f"{v}/logs", exist_ok=True)
    for r in rows:
        _link(f"{C.LAYOUT}/logs/run_{r['run']}.jsonl", f"{v}/logs/run_{r['run']}.jsonl")
    with open(f"{v}/logs/results.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    if C.SCRATCH:
        os.makedirs(f"{v}/{C.SCRATCH_DIR}")                # 31.10: единственное место, куда можно писать
    return os.path.realpath(v)


def _inside(path, base):
    base = os.path.realpath(base)
    return path == base or path.startswith(base + os.sep)


def _link(src, dst, base=None):
    """Жёсткие ссылки src -> dst. v3c: только обычные файлы, симлинки не разыменовываются и пропускаются
    (и файлы, и каталоги), realpath(src) обязан лежать внутри base (по умолчанию LAYOUT)."""
    base = C.LAYOUT if base is None else base
    st = os.lstat(src)
    if stat.S_ISLNK(st.st_mode):
        return
    if not _inside(os.path.realpath(src), base):        # путь через симлинк-каталог наружу
        raise ValueError(f"_link: {src} is outside {base}")
    if not stat.S_ISDIR(st.st_mode):
        if stat.S_ISREG(st.st_mode):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.link(src, dst, follow_symlinks=False)
        return
    for root, _, files in os.walk(src):              # followlinks=False: в симлинк-каталоги не заходим
        r = os.path.join(dst, os.path.relpath(root, src))
        os.makedirs(r, exist_ok=True)
        for f in files:
            s = os.path.join(root, f)
            if stat.S_ISREG(os.lstat(s).st_mode) and _inside(os.path.realpath(s), base):
                os.link(s, os.path.join(r, f), follow_symlinks=False)
