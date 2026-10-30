"""Цикл coding-агента на 9B: общий для исследователя и редактора.

Инструменты: bash только на чтение (песочница sandbox-exec), инструменты роли (report / edit), finish.
Механика сессии (политика `final`, калибровка 29.10): лимит вызовов bash, повтор команды не исполняется,
3 повтора подряд, лимит или край окна -> финал: несколько ходов только с инструментами роли и finish.

Изоляция — профиль sandbox-exec: deny default; исполнять можно только bash и программы из ALLOWED, читать —
только каталог сессии и сами эти программы; записи и сети нет. python3 в песочнице может то же, что bash,
поэтому граница — профиль. Разбор команды до запуска и подсказки к выводу (shell.py) — то, что видит модель:
понятный отказ вместо «Operation not permitted», заметки к пустому выводу и ошибкам, обрезка с указанием, как дочитать. «/» = корень каталога сессии, как смонтированный образ: аргументы
«/…» и пути python3 переводятся в каталог, в выводе путь каталога -> «/» (песочница та же, это только пути).
"""
import json
import os
import re
import selectors
import signal
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.request

import shell

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "bin")                       # runs и python3 (ссылка на CLT python: /usr/bin/python3 —
PY_LINK = os.path.join(BIN, "python3")                # обёртка xcode-select, в песочнице не работает)
SITE = os.path.join(HERE, "site")                     # sitecustomize.py: «/» = корень каталога и для python3
URL = os.environ.get("NRHSI_URL", "http://127.0.0.1:8089/v1/chat/completions")
MODEL = os.environ.get("NRHSI_MODEL", "ornith15-9b")

CTX = 65536              # окно воркера
MAX_GEN = 4096
HARD_AT = 52000          # оценка промпта -> финал
FINAL_TURNS = 4
FINAL_FIX_TURNS = 2      # ход финала с отклонённым вызовом роли не считается (не больше стольких раз)
REPEAT_STOP = 3          # столько повторов команды подряд -> финал
MAX_NO_CALL = 6
OUT_CHARS = 8000         # вывод bash, который видит модель
CMD_TIMEOUT = 20
MAX_CAPTURE = 200_000
TEMP = 0.6

ALLOWED = ["[", "awk", "basename", "cat", "column", "comm", "cut", "diff", "dirname", "echo", "expr", "false", "find",
           "grep", "head", "jq", "ls", "nl", "od", "paste", "printf", "rev", "sed", "seq", "sort", "tail", "test",
           "tr", "true", "uniq", "wc", "which", "xargs", "xxd", "python3", "runs"]
BUILTINS = [":", "[[", "break", "cd", "command", "continue", "pwd", "read"]          # встроенные bash: в промпте, в профиле не нужны
shell.ALLOWED = set(ALLOWED + BUILTINS)
shell.OUT_CHARS, shell.MAX_CAPTURE = OUT_CHARS, MAX_CAPTURE

REPEAT_MSG = "Don't repeat yourself."
EXAMPLES = {}            # инструмент роли -> пример вызова для отказа «это инструмент, не команда» (задаёт роль)
NO_CALL_MSG = "Your reply contained no tool call. Continue with the tools; call finish when you are done."

BASH_TOOL = {"type": "function", "function": {
    "name": "bash", "description": "Run a read-only shell command in the working directory. Pipes, ';', '&&', '||', "
    "$(...), for/while loops and if work; nothing can be written. Long output is truncated: use grep -n, sed -n 'a,bp', head, tail.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The command line"}},
                   "required": ["command"]}}}
FINISH_TOOL = {"type": "function", "function": {
    "name": "finish", "description": "End the session.", "parameters": {"type": "object", "properties": {}}}}

BASH_LINE = (f"- bash(command): a read-only shell in the working directory. Programs: {', '.join(sorted(ALLOWED + BUILTINS))}. Pipes, ';', "
             f"'&&', '||', $(...), for/while loops and if work. Nothing can be written (no files, no /tmp). Output longer "
             f"than {OUT_CHARS} characters is truncated, so read big files in parts (sed -n '40,90p' FILE, head, tail) "
             "and search with grep -n")
BSD_LINE = ("- The shell is bash 3.2 with macOS/BSD utilities: GNU-only options are missing (use grep -E, not grep -P; "
            "no find -printf).")
PY_LINE = "- python3 is available (standard library; no network, nothing can be written)."


# ---------------------------------------------------------------- песочница

def _ancestors(p):
    out = []
    while p not in ("/", ""):
        out.append(p)
        p = os.path.dirname(p)
    return out


def sandbox_profile(root):
    progs = {"/bin/bash"}
    for p in set(ALLOWED) - {"python3", "runs"}:          # /usr/bin/python3 — обёртка xcode-select, не нужна
        for d in ("/usr/bin", "/bin"):
            if os.access(f"{d}/{p}", os.X_OK):
                progs.add(f"{d}/{p}")
    clt = os.readlink(PY_LINK)                                        # /Library/Developer/CommandLineTools/usr/bin/python3
    launcher = os.path.realpath(PY_LINK)                              # .../Python3.framework/Versions/X/bin/python3.X
    ver = os.path.dirname(os.path.dirname(launcher))
    fw = os.path.dirname(os.path.dirname(ver))
    app = os.path.join(ver, "Resources/Python.app/Contents/MacOS/Python")
    progs |= {launcher, app, os.path.join(BIN, "runs")}
    reads = [BIN, PY_LINK, os.path.join(BIN, "runs"), clt, os.path.dirname(clt)]
    meta = ["/"] + sorted({a for p in (BIN, clt, launcher) for a in _ancestors(os.path.dirname(p))})
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
(allow file-read* {lit(reads)} (subpath "{fw}") (subpath "{SITE}"))
(allow file-read-metadata {lit(meta)})
"""
    path = f"{root}.sb"                                                  # рядом с каталогом, не внутри
    with open(path, "w") as f:
        f.write(text)
    return path


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
           f'command {p} "${{__A[@]}}"; }}' for p in sorted(set(ALLOWED) - NO_WRAP)]
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
    text = re.sub(r'  File "' + re.escape(SITE) + r'/sitecustomize\.py", line \d+, in \w+\n[^\n]*\n', "", text)
    text = re.sub(r"/bin/bash: line \d+: ", "bash: ", text)       # номер строки — с учётом пролога
    return text.replace(BIN, "/usr/local/bin").replace(root + "/", "/").replace(root, "/")


def run_bash(cmd, root, prof):
    """-> (вывод для модели, исполнена ли). Сначала разбор (shell.check_command): отказ — без запуска.
    Своя группа процессов: по таймауту или потолку вывода убивается вся."""
    body = None
    hd = shell.split_heredoc(cmd)
    if hd:
        cmd, body = hd
    parsed, pipeamp = [], []
    err = shell.check_command(cmd, parsed, pipeamp)
    if err:
        return f"Error: {err}", False
    raw = cmd
    for j in reversed(pipeamp):
        cmd = cmd[:j] + " 2>&1 |" + cmd[j + 2:]
    env = {"PATH": f"{BIN}:/usr/bin:/bin", "LANG": "en_US.UTF-8", "HOME": root, "PYTHONDONTWRITEBYTECODE": "1",
           "RUNS_OUT_CHARS": str(OUT_CHARS), "NRHSI_ROOT": root, "PYTHONPATH": SITE, "NRHSI_SYS": BIN}
    p = subprocess.Popen(["sandbox-exec", "-f", prof, "/bin/bash", "--noprofile", "--norc", "-c",
                          root_prelude(root) + cmd], cwd=root,
                         stdin=subprocess.DEVNULL if body is None else subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True, env=env)
    if body is not None:
        threading.Thread(target=_feed, args=(p.stdin, body.encode()), daemon=True).start()
    deadline = time.monotonic() + CMD_TIMEOUT
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
            capped = len(bufs[p.stdout]) > MAX_CAPTURE
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
        return f"Error: command timed out after {CMD_TIMEOUT}s; narrow it (search fewer files, use head).", False
    out = root_paths(bufs[p.stdout][:MAX_CAPTURE].decode("utf-8", "replace"), root)
    err = root_paths(bufs[p.stderr][:20_000].decode("utf-8", "replace"), root)
    err = shell.XARGS_PIPE_RE.sub("", err)              # ... | xargs ... | head: xargs жалуется на закрытый пайп
    text = out + (("\n[stderr]\n" + err) if err.strip() else "")
    if rc and not text.strip():
        text = f"(no output, exit code {rc})"
    elif not text:
        text = "(no output)"
    notes = []
    note = shell._stdin_note(parsed, raw, empty=not out.strip())
    if note:
        notes.append(note)
    if err.strip():
        notes += shell._layout_notes(raw, err, root) + shell._bsd_notes(err)
    text, _ = shell.clip(text, raw, root, capped, parsed)
    if notes:
        text += "\n" + "\n".join(f"[note: {n}]" for n in notes)
    return text, True


def _feed(f, data):
    try:
        f.write(data)
        f.close()
    except OSError:
        pass


# ---------------------------------------------------------------- модель

def chat(messages, tools, seed):
    body = {"model": MODEL, "messages": messages, "temperature": TEMP, "seed": seed, "max_tokens": MAX_GEN,
            "tools": tools}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                resp = json.load(r)
            ch = resp["choices"][0]
            msg = ch["message"]
            calls = [{"id": c.get("id") or f"call_{seed}_{i}", "type": "function",
                      "function": {"name": c["function"]["name"], "arguments": c["function"].get("arguments") or ""}}
                     for i, c in enumerate(msg.get("tool_calls") or []) if c.get("function", {}).get("name")]
            return {"content": msg.get("content") or "", "calls": calls, "usage": resp.get("usage") or {},
                    "finish_reason": ch.get("finish_reason")}
        except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
            time.sleep(5)
    raise RuntimeError(f"model call failed: {err}")


def est_tokens(text):
    return int(len(text) / 3.0) + 8


# ---------------------------------------------------------------- сессия

def session(system, first_user, role_tools, handle, root, log_path, bash_limit, final_msg, seed=1):
    """role_tools — схемы инструментов роли; handle(name, args) -> (текст для модели, принят ли вызов).
    Пишет log_path (jsonl: meta, turn..., end) и возвращает причину конца."""
    root = os.path.realpath(root)
    tools = [BASH_TOOL] + role_tools + [FINISH_TOOL]
    shell.TOOLS = {t["function"]["name"]: EXAMPLES.get(t["function"]["name"], "") for t in tools[1:]}
    final_tools = role_tools + [FINISH_TOOL]
    prof = sandbox_profile(root)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": first_user}]
    seen, repeats, bash_calls, no_call, turns = set(), 0, 0, 0, 0
    final_left = fix_left = 0
    est, end = 0, None
    log = open(log_path, "w", encoding="utf-8")

    def w(rec):
        log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.flush()

    def say(text):
        nonlocal est
        messages.append({"role": "user", "content": text})
        est += est_tokens(text)

    def enter_final():
        nonlocal final_left, fix_left
        final_left, fix_left = FINAL_TURNS, FINAL_FIX_TURNS
        say(final_msg)

    w({"type": "meta", "system": system, "first_user": first_user, "tools": [t["function"]["name"] for t in tools],
       "root": root, "seed": seed, "bash_limit": bash_limit})
    try:
        while end is None:
            if est >= HARD_AT and not final_left:
                enter_final()
            if est >= CTX - MAX_GEN - 1500:
                end = "forced: context full"
                break
            t0 = time.time()
            r = chat(messages, final_tools if final_left else tools, seed + turns)
            turns += 1
            u = r["usage"]
            est = (u.get("prompt_tokens") or est) + (u.get("completion_tokens") or 0)
            amsg = {"role": "assistant", "content": r["content"]}
            if r["calls"]:
                amsg["tool_calls"] = r["calls"]
            messages.append(amsg)
            rec = {"type": "turn", "i": turns, "sec": round(time.time() - t0, 1), "usage": u, "final": bool(final_left),
                   "content": r["content"], "results": []}
            finished = rejected = False
            if not r["calls"]:
                no_call += 1
                say(NO_CALL_MSG)
                end = "forced: no tool calls" if no_call >= MAX_NO_CALL else None
            for c in r["calls"]:
                name, raw = c["function"]["name"], c["function"]["arguments"]
                try:
                    args = json.loads(raw) if raw else {}
                    args = args if isinstance(args, dict) else {}
                except ValueError:
                    args = None
                if args is None:
                    out, ok = "Error: could not parse the arguments as JSON. Call the tool again with valid JSON arguments.", False
                elif name == "finish":
                    out, ok, finished = "Finished.", True, True
                elif name == "bash" and not final_left:
                    cmd = str(args.get("command", ""))
                    key = " ".join(cmd.split())
                    bash_calls += 1                      # лимит считает все вызовы bash, и повторы тоже
                    if key in seen:
                        repeats += 1
                        out, ok = REPEAT_MSG, False
                    else:
                        seen.add(key)
                        out, ok = run_bash(cmd, root, prof)
                elif name in [t["function"]["name"] for t in role_tools]:
                    try:
                        out, ok = handle(name, args)
                    except Exception as e:  # noqa: BLE001  ответ модели не роняет сессию
                        out, ok = f"Error: {type(e).__name__}: {str(e)[:300]}", False
                    if ok and name == "edit":
                        seen.clear()                     # файлы изменились: прежние команды снова осмысленны
                    rejected |= not ok
                else:
                    names = ", ".join(t["function"]["name"] for t in (final_tools if final_left else tools))
                    out, ok = f"Error: unknown tool '{name}' here. Tools: {names}.", False
                if out != REPEAT_MSG:
                    repeats = 0                          # повторы считаются подряд
                rec["results"].append({"name": name, "arguments": raw, "ok": ok, "out": out})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
                est += est_tokens(out) + 10
                if finished:
                    break
            w(rec)
            if end:
                break
            if finished:
                end = "finish"
            elif final_left:
                if rejected and fix_left:
                    fix_left -= 1
                else:
                    final_left -= 1
                    end = None if final_left else "forced: final turns used"
            elif repeats >= REPEAT_STOP or bash_calls >= bash_limit:
                enter_final()
    except Exception as e:  # noqa: BLE001
        end = f"forced: {type(e).__name__}: {e}"[:300]
        w({"type": "error", "traceback": traceback.format_exc()[-4000:]})
    finally:
        w({"type": "end", "reason": end or "forced: interrupted", "turns": turns, "bash_calls": bash_calls})
        log.close()
        os.unlink(prof)
    return end
