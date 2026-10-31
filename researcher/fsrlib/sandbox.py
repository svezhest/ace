"""Песочница и исполнение: профиль sandbox-exec, «/» = корень вида, run_bash, bash_output."""
import atexit
import os
import re
import selectors
import signal
import subprocess
import threading
import time

from . import cfg as C
from . import check as K
from . import notes as N


# ---------------------------------------------------------------- песочница

_PROFILES = []          # профили этого процесса: удаляются при выходе


@atexit.register
def _rm_profiles():
    for p in _PROFILES:
        try:
            os.unlink(p)
        except OSError:
            pass


def exec_programs():
    """Пути программ белого списка (PATH=/usr/bin:/bin) и /bin/bash: только их разрешает process-exec.
    Встроенные (cd, read) — не программы: /usr/bin/cd, /usr/bin/read — обёртки на /bin/sh, их не берём."""
    out = {"/bin/bash"}
    for p in C.ALLOWED - C.BUILTINS - {"python3", "runs"}:
        for d in ("/usr/bin", "/bin"):
            f = f"{d}/{p}"
            if os.path.isfile(f) and os.access(f, os.X_OK):
                out.add(f)
    if {"python3", "runs"} & C.ALLOWED:
        py = py_paths()
        out |= {py["launcher"], py["app"]}
    if "runs" in C.ALLOWED:
        out.add(os.path.join(C.BIN, "runs"))
    return sorted(out)


def py_paths():
    """29.10: python3 для песочницы. bin/python3 -> PY_LINK -> .../Python3.framework/Versions/X/bin/python3.X —
    запускалка, она порождает Resources/Python.app/Contents/MacOS/Python. -> пути для профиля."""
    launcher = os.path.realpath(C.PY_LINK)
    ver = os.path.dirname(os.path.dirname(launcher))                 # .../Python3.framework/Versions/3.9
    fw = os.path.dirname(os.path.dirname(ver))                       # .../Python3.framework
    app = os.path.join(ver, "Resources/Python.app/Contents/MacOS/Python")
    assert fw.endswith(".framework") and os.path.isfile(app), (launcher, app)
    return {"launcher": launcher, "app": app, "framework": fw, "link": C.PY_LINK}


def _ancestors(p):
    out = []
    while p not in ("/", ""):
        out.append(p)
        p = os.path.dirname(p)
    return out


def profile_text(root):
    """v3c: (deny default) и явные allow; обоснование каждого — journal.md, «Механика v3c».
    exec — только bash и программы белого списка; чтение — вид, эти программы, локаль, /dev/null|urandom|fd/N;
    «/» (file-read-data) — без него dyld роняет процесс (SIGABRT); sysctl-read — dyld/libc при старте."""
    lit = lambda ps: " ".join(f'(literal "{p}")' for p in ps)      # noqa: E731
    progs = exec_programs()
    return f"""(version 1)
(deny default)
(allow process-fork)
(allow process-exec {lit(progs)})
(allow file-read* {lit(progs)})
(allow file-read-data (literal "/"))
(allow file-read* (subpath "/usr/share/locale"))
(allow sysctl-read)
(allow file-read* (literal "/dev/null") (literal "/dev/urandom") (regex #"^/dev/fd/[0-9]+$"))
(allow file-write-data (literal "/dev/null"))
(allow file-read* (subpath "{root}"))
(allow file-read-metadata (literal "{os.path.dirname(root)}"))
""" + _py_profile()


def _py_profile():
    """29.10 (PYTHON / RUNS_TOOL): чтение stdlib (каталог фреймворка), bin/ и цепочки ссылок до запускалки;
    метаданные предков — для realpath запускалки. Запись и сеть — как у всех: deny default."""
    if not {"python3", "runs"} & C.ALLOWED:
        return ""
    py = py_paths()
    lit = lambda ps: " ".join(f'(literal "{p}")' for p in ps)      # noqa: E731
    reads = [C.BIN, os.path.join(C.BIN, "python3"), py["link"], os.path.dirname(py["link"])]
    if "runs" in C.ALLOWED:
        reads.append(os.path.join(C.BIN, "runs"))
    meta = ["/"] + sorted({a for p in (C.BIN, py["link"], py["launcher"]) for a in _ancestors(os.path.dirname(p))})
    return (f'(allow file-read* {lit(reads)} (subpath "{py["framework"]}") (subpath "{C.SITE}"))\n'
            f"(allow file-read-metadata {lit(meta)})\n")


def sandbox_profile(root, name=None):
    """Профиль sandbox-exec для вида root. v3c: имя уникально на процесс (pid), запись атомарная, файл
    удаляется при выходе — параллельные сессии/тесты не перетирают чужой профиль."""
    os.makedirs(f"{C.HERE}/views", exist_ok=True)
    p = os.path.abspath(f"{C.HERE}/views/.sb_{name or os.path.basename(root)}_{os.getpid()}.sb")
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(profile_text(root))
    os.replace(tmp, p)
    if p not in _PROFILES:
        _PROFILES.append(p)
    return p


# ---------------------------------------------------------------- исполнение

def _killpg(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _exited(pid, timeout):
    """Ждать завершения лидера, не собирая его (WNOWAIT): pid остаётся занятым до p.wait(). -> завершился ли."""
    end, d = time.monotonic() + timeout, 0.001
    while True:
        try:
            if os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is not None:
                return True
        except ChildProcessError:
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(d)
        d = min(d * 2, 0.02)


def _collect(p, deadline):
    """stdout и stderr потоком до EOF/срока; stdout не больше MAX_CAPTURE байт (дальше — capped), stderr
    дочитывается, но хранится не больше MAX_STDERR. -> (stdout, stderr, capped, timed_out)"""
    sel = selectors.DefaultSelector()
    bufs = {p.stdout: bytearray(), p.stderr: bytearray()}
    caps = {p.stdout: C.MAX_CAPTURE, p.stderr: C.MAX_STDERR}
    for f in bufs:
        sel.register(f, selectors.EVENT_READ)
    capped = timed = False
    while sel.get_map() and not capped:
        left = deadline - time.monotonic()
        if left <= 0:
            timed = True
            break
        for key, _ in sel.select(timeout=left):
            f = key.fileobj
            chunk = os.read(f.fileno(), 65536)
            if not chunk:
                sel.unregister(f)
                continue
            b = bufs[f]
            room = caps[f] - len(b)
            b += chunk[:max(0, room)]
            if f is p.stdout and len(chunk) > room:
                capped = True
    sel.close()
    return bytes(bufs[p.stdout]), bytes(bufs[p.stderr]), capped, timed


# «/» = корень вида (как смонтированный образ): функции bash поверх программ белого списка переводят аргументы-пути.
NO_WRAP = {"cd", "read", "break", "continue", ":", "[[", "[", "test", "echo", "printf", "true", "false", "basename",
           "dirname", "expr", "seq", "tr", "runs", "pwd", "which", "command"}
PATTERN_FIRST = {"grep", "sed", "awk", "jq"}                    # первый операнд — шаблон или программа, не путь
VALUE_OPTS = {                                                  # опции со значением в следующем слове: значение не путь
    "cut": "-d -f -c -b", "sort": "-t -k -T -S", "paste": "-d", "column": "-s -c", "awk": "-F -v",
    "xargs": "-d -I -E -n -P -L -s", "grep": "-A -B -C -m -d -D --include --exclude --exclude-dir --context",
    "find": "-name -iname -regex -iregex -type -maxdepth -mindepth -size -perm -user -group -mtime -mmin",
    "python3": "-c -m -W -X", "jq": "--arg --argjson --indent", "od": "-A -j -N -t", "xxd": "-c -g -l -s -o",
    "nl": "-b -d -f -h -i -l -n -s -v -w", "uniq": "-f -s", "head": "-n -c", "tail": "-n -c"}
PATH_OPTS = {"find": "-path -ipath -newer"}                     # значение — путь (шаблон пути): переводится без glob


def root_prelude(root):
    """«/» = корень каталога, как в смонтированном образе: аргумент «/путь» вне каталога -> «каталог/путь» (кроме /dev),
    «..» из корня -> корень; cd за пределы -> корень (относительный путь) или «No such file» (абсолютный).
    Песочница та же: функции только переписывают аргументы."""
    fns = [f'{p}(){{ __m {int(p in PATTERN_FIRST)} "{VALUE_OPTS.get(p, "")}" "{PATH_OPTS.get(p, "")}" "$@"; '
           f'command {p} "${{__A[@]}}"; }}' for p in sorted(set(C.ALLOWED) - NO_WRAP)]
    return ("__R='" + root.replace("'", "'\\''") + "'\n"
            "__p(){ if [[ $1 == / || $1 == /. ]]; then __A+=(\"$__R\")\n"
            "  elif [[ $PWD == \"$__R\" && ( $1 == .. || $1 == ../* ) ]]; then local g=$1; "
            "while [[ $g == .. || $g == ../* ]]; do g=${g#..}; g=${g#/}; done; __A+=(\"$__R/$g\")\n"
            "  elif [[ $1 == /* && $1 != \"$__R\" && $1 != \"$__R\"/* && $1 != /dev/* ]]; then\n"
            "    if [[ $2 == 0 && $1 == *[*?[]* ]]; then local g=( $__R$1 ); if [[ -e ${g[0]} ]]; then __A+=(\"${g[@]}\"); "
            "else __A+=(\"$__R$1\"); fi; else __A+=(\"$__R$1\"); fi\n"
            "  else __A+=(\"$1\"); fi; }\n"
            "__m(){ local s=$1 v=\" $2 \" w=\" $3 \" a o=0 k=0; shift 3; __A=(); for a in \"$@\"; do\n"
            "  if [[ $k == 1 ]]; then k=0; __A+=(\"$a\"); continue; fi\n"
            "  if [[ $k == 2 ]]; then k=0; __p \"$a\" 1; continue; fi\n"
            "  if [[ $a == -?* ]]; then __A+=(\"$a\")\n"
            "    if [[ $v == *\" $a \"* ]]; then k=1; elif [[ $w == *\" $a \"* ]]; then k=2; fi\n"
            "    if [[ $s == 1 && ( $a == -e || $a == --regexp ) ]]; then o=1; k=1; elif [[ $s == 1 && ( $a == -f || $a == --file ) ]]; then o=1; fi\n"
            "    continue; fi\n"
            "  if [[ $s == 1 && $o == 0 ]]; then o=1; __A+=(\"$a\"); continue; fi\n"
            "  __p \"$a\" 0; done; }\n"
            "cd(){ local t; if [[ $# == 0 ]]; then builtin cd \"$__R\"; return; fi; __m 0 \"\" \"\" \"$@\"; "
            "t=$(builtin cd \"${__A[@]}\" 2>/dev/null && builtin pwd -P 2>/dev/null); "
            "if [[ $t == \"$__R\" || $t == \"$__R\"/* ]]; then builtin cd \"${__A[@]}\"; "
            "elif [[ ${__A[0]} == /* ]]; then builtin cd \"${__A[@]}\"; "
            "elif (builtin cd \"${__A[@]}\" 2>/dev/null); then builtin cd \"$__R\"; else builtin cd \"${__A[@]}\"; fi; }\n"
            "command(){ if [[ $1 == -v || $1 == -V ]]; then shift; /usr/bin/which \"$@\"; else builtin command \"$@\"; fi; }\n"
            + "\n".join(fns) + "\n")


def root_paths(text, root):
    text = re.sub(r'  File "' + re.escape(C.SITE) + r'/sitecustomize\.py", line \d+, in \w+\n[^\n]*\n', "", text)
    text = re.sub(r"/bin/bash: line \d+: ", "bash: ", text)       # номер строки — с учётом пролога
    return text.replace(C.BIN, "/usr/local/bin").replace(root + "/", "/").replace(root, "/")


def run_bash(cmd, root, prof, info=None):
    """-> (ok, text). v3: своя группа процессов (по таймауту/потолку убивается вся, сирот нет), stdin=/dev/null,
    вывод читается потоком с потолком MAX_CAPTURE. info <- pid, rc, capped, timed_out, parsed, notes."""
    info = {} if info is None else info
    parsed, pipeamp = [], []
    body = None
    if C.PYTHON:
        hd = K.split_heredoc(cmd)
        if hd:
            cmd, body = hd
            info["heredoc"] = True
    err = K.check_command(cmd, parsed, pipeamp)
    info.update(parsed=parsed, notes=[], capped=False, timed_out=False, pid=None, rc=None)
    if err:
        return False, f"Error: {err}"
    run = cmd
    for j in reversed(pipeamp):
        run = run[:j] + " 2>&1 |" + run[j + 2:]
    deadline = time.monotonic() + C.CMD_TIMEOUT
    env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "HOME": root}
    if C.PYTHON or C.RUNS_TOOL:
        env.update(PATH=f"{C.BIN}:/usr/bin:/bin", PYTHONDONTWRITEBYTECODE="1", RUNS_OUT_CHARS=str(C.OUT_CHARS), RUNS_FORMAT=C.RUNS_FORMAT)
    run = root_prelude(root) + run
    env.update(NRHSI_ROOT=root, PYTHONPATH=C.SITE, NRHSI_SYS=C.BIN)
    p = subprocess.Popen(["sandbox-exec", "-f", prof, "/bin/bash", "--noprofile", "--norc", "-c", run],
                         cwd=root, stdin=subprocess.DEVNULL if body is None else subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env=env)
    if body is not None:
        threading.Thread(target=_feed, args=(p.stdin, body.encode("utf-8")), daemon=True).start()
    info["pid"] = p.pid
    out = er = b""
    capped = timed = False
    try:
        out, er, capped, timed = _collect(p, deadline)
        if not (capped or timed) and not _exited(p.pid, max(0.5, deadline - time.monotonic())):
            timed = True
    finally:
        # v3c: группа убивается до reap. Пока лидер не собран (жив или зомби), его pid = pgid занят и не может
        # достаться чужой группе; после p.wait() killpg мог бы попасть в чужую. Остатки группы (процесс закрыл
        # вывод и работает дальше) гибнут здесь же.
        _killpg(p.pid)
        rc = p.wait()
        p.stdout.close()
        p.stderr.close()
    info.update(rc=rc, capped=capped, timed_out=timed)
    if timed:
        return False, (f"Error: the command did not end within {C.CMD_TIMEOUT}s and was stopped (a search over many "
                       "files, or a program that does not end).")
    out = out.decode("utf-8", "replace")
    out, er = root_paths(out, root), root_paths(er.decode("utf-8", "replace"), root)
    er = N.XARGS_PIPE_RE.sub("", er)                      # ... | xargs ... | head: xargs жалуется на закрытый пайп
    text = out + (("\n[stderr]\n" + er) if er.strip() else "")
    if rc and not text.strip():
        text = f"(no output, exit code {rc})"
    elif not text:
        text = "(no output)"
    note = N._stdin_note(parsed, cmd, empty=not out.strip())
    if note:
        info["notes"].append(note)
    if er.strip():
        info["notes"] += N._layout_notes(cmd, er, root) + N._bsd_notes(er)
    return True, text


def _feed(f, data):
    """Тело heredoc -> stdin команды (в потоке: команда может не читать stdin, пайп не должен зависнуть)."""
    try:
        f.write(data)
    except OSError:
        pass
    finally:
        try:
            f.close()
        except OSError:
            pass


def bash_output(cmd, root, prof):
    """Команда -> (ok, что видит модель, полный вывод, info, обрезано ли). Заметки идут после обрезки."""
    info = {}
    ok, full = run_bash(cmd, root, prof, info)
    shown, tr = N.clip(full, cmd, root, info.get("capped"), info.get("parsed"))
    if info.get("notes"):
        shown += "\n" + "\n".join(f"[note: {n}]" for n in info["notes"])
    return ok, shown, full, info, tr
