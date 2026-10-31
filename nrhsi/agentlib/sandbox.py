"""Песочница и исполнение: профиль sandbox-exec, «/» = корень каталога сессии, run_bash."""
import os
import re
import selectors
import signal
import subprocess
import threading
import time

from . import cfg as C


def _ancestors(p):
    out = []
    while p not in ("/", ""):
        out.append(p)
        p = os.path.dirname(p)
    return out


def sandbox_profile(root):
    progs = {"/bin/bash"}
    for p in set(C.ALLOWED) - {"python3", "runs"}:        # /usr/bin/python3 — обёртка xcode-select, не нужна
        for d in ("/usr/bin", "/bin"):
            if os.access(f"{d}/{p}", os.X_OK):
                progs.add(f"{d}/{p}")
    clt = os.readlink(C.PY_LINK)                                      # /Library/Developer/CommandLineTools/usr/bin/python3
    launcher = os.path.realpath(C.PY_LINK)                            # .../Python3.framework/Versions/X/bin/python3.X
    ver = os.path.dirname(os.path.dirname(launcher))
    fw = os.path.dirname(os.path.dirname(ver))
    app = os.path.join(ver, "Resources/Python.app/Contents/MacOS/Python")
    progs |= {launcher, app, os.path.join(C.BIN, "runs")}
    reads = [C.BIN, C.PY_LINK, os.path.join(C.BIN, "runs"), clt, os.path.dirname(clt)]
    meta = ["/"] + sorted({a for p in (C.BIN, clt, launcher) for a in _ancestors(os.path.dirname(p))})
    lit = lambda ps: " ".join(f'(literal "{p}")' for p in sorted(ps))   # noqa: E731
    text = f"""(version 1)
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
(allow file-read* {lit(reads)} (subpath "{fw}") (subpath "{C.SITE}"))
(allow file-read-metadata {lit(meta)})
"""
    path = f"{root}.sb"                                                  # рядом с каталогом, не внутри
    with open(path, "w") as f:
        f.write(text)
    return path


HEREDOC_RE = re.compile(r"\s*python3(?:[ \t]+-)?[ \t]*<<(-?)[ \t]*(['\"]?)([A-Za-z_]\w*)\2([^\n]*)\n")


def split_heredoc(cmd):
    """python3 - <<'EOF' ... EOF -> ("python3 -", тело в stdin): here-doc bash пишет во временный файл, а писать нельзя."""
    m = HEREDOC_RE.match(cmd)
    if not m:
        return cmd, None
    tabs, word, body = m.group(1) == "-", m.group(3), []
    lines = cmd[m.end():].split("\n")
    for i, ln in enumerate(lines):
        x = ln.lstrip("\t") if tabs else ln
        if x.rstrip() == word:
            if "\n".join(lines[i + 1:]).strip():
                return cmd, None
            break
        body.append(x)
    return "python3 -" + m.group(4), "\n".join(body) + "\n"


NO_WRAP = {"cd", "read", "break", "continue", ":", "[[", "[", "test", "echo", "printf", "true", "false", "basename",
           "dirname", "expr", "seq", "tr", "runs"}
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
            + "\n".join(fns) + "\n")


def root_paths(text, root):
    text = re.sub(r'  File "' + re.escape(C.SITE) + r'/sitecustomize\.py", line \d+, in \w+\n[^\n]*\n', "", text)
    text = re.sub(r"/bin/bash: line \d+: ", "bash: ", text)       # номер строки — с учётом пролога
    return text.replace(C.BIN, "/usr/local/bin").replace(root + "/", "/").replace(root, "/")


def run_bash(cmd, root, prof):
    """-> вывод для модели. Своя группа процессов: по таймауту или потолку вывода убивается вся."""
    cmd, body = split_heredoc(cmd)
    env = {"PATH": f"{C.BIN}:/usr/bin:/bin", "LANG": "en_US.UTF-8", "HOME": root, "PYTHONDONTWRITEBYTECODE": "1",
           "RUNS_OUT_CHARS": str(C.OUT_CHARS), "NRHSI_ROOT": root, "PYTHONPATH": C.SITE, "NRHSI_SYS": C.BIN}
    p = subprocess.Popen(["sandbox-exec", "-f", prof, "/bin/bash", "--noprofile", "--norc", "-c",
                          root_prelude(root) + cmd], cwd=root,
                         stdin=subprocess.DEVNULL if body is None else subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True, env=env)
    if body is not None:
        threading.Thread(target=_feed, args=(p.stdin, body.encode()), daemon=True).start()
    deadline = time.monotonic() + C.CMD_TIMEOUT
    sel, bufs = selectors.DefaultSelector(), {p.stdout: bytearray(), p.stderr: bytearray()}
    for f in bufs:
        sel.register(f, selectors.EVENT_READ)
    timed = capped = False
    while sel.get_map() and not capped:
        left = deadline - time.monotonic()
        if left <= 0:
            timed = True
            break
        for key, _ in sel.select(timeout=left):
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                sel.unregister(key.fileobj)
            bufs[key.fileobj] += chunk
            capped = len(bufs[p.stdout]) > C.MAX_CAPTURE
    sel.close()
    if not timed and not capped:
        try:
            p.wait(timeout=max(0.5, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            timed = True
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    rc = p.wait()
    if timed:
        return f"Error: command timed out after {C.CMD_TIMEOUT}s; narrow it (search fewer files, use head)."
    out = root_paths(bufs[p.stdout][:C.MAX_CAPTURE].decode("utf-8", "replace"), root)
    err = root_paths(bufs[p.stderr][:20_000].decode("utf-8", "replace"), root)
    text = out + (("\n[stderr]\n" + err) if err.strip() else "")
    if not text.strip():
        text = f"(no output, exit code {rc})" if rc else "(no output)"
    if len(text) > C.OUT_CHARS:
        text = (text[:C.OUT_CHARS] + f"\n\n[output truncated: showing the first {C.OUT_CHARS} of {len(text)} characters. "
                "Read on with sed -n 'a,bp' or narrow it with grep -n.]")
    return text


def _feed(f, data):
    try:
        f.write(data)
        f.close()
    except OSError:
        pass
