"""Цикл coding-агента на 9B: общий для исследователя и редактора.

Инструменты: bash только на чтение (песочница sandbox-exec), инструменты роли (report / edit), finish.
Механика сессии (политика `final`, калибровка 29.10): лимит вызовов bash, повтор команды не исполняется,
3 повтора подряд, лимит или край окна -> финал: несколько ходов только с инструментами роли и finish.

Изоляция — профиль sandbox-exec: deny default; исполнять можно только bash и программы из ALLOWED, читать —
только каталог сессии и сами эти программы; записи и сети нет. python3 в песочнице может то же, что bash,
поэтому граница — профиль, а не разбор команд.
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

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "bin")                       # runs и python3 (ссылка на CLT python: /usr/bin/python3 —
PY_LINK = os.path.join(BIN, "python3")                # обёртка xcode-select, в песочнице не работает)
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
           "tr", "true", "uniq", "wc", "xargs", "xxd", "python3", "runs"]
BUILTINS = [":", "[[", "break", "cd", "continue", "read"]          # встроенные bash: в промпте, в профиле не нужны

REPEAT_MSG = "Don't repeat yourself."
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
(allow file-read* {lit(reads)} (subpath "{fw}"))
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


def run_bash(cmd, root, prof):
    """-> вывод для модели. Своя группа процессов: по таймауту или потолку вывода убивается вся."""
    cmd, body = split_heredoc(cmd)
    env = {"PATH": f"{BIN}:/usr/bin:/bin", "LANG": "en_US.UTF-8", "HOME": root, "PYTHONDONTWRITEBYTECODE": "1",
           "RUNS_OUT_CHARS": str(OUT_CHARS)}
    p = subprocess.Popen(["sandbox-exec", "-f", prof, "/bin/bash", "--noprofile", "--norc", "-c", cmd], cwd=root,
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
        return f"Error: command timed out after {CMD_TIMEOUT}s; narrow it (search fewer files, use head)."
    out = bufs[p.stdout][:MAX_CAPTURE].decode("utf-8", "replace")
    err = bufs[p.stderr][:20_000].decode("utf-8", "replace").replace(root + "/", "").replace(root, ".")
    text = out + (("\n[stderr]\n" + err) if err.strip() else "")
    if not text.strip():
        text = f"(no output, exit code {rc})" if rc else "(no output)"
    if len(text) > OUT_CHARS:
        text = (text[:OUT_CHARS] + f"\n\n[output truncated: showing the first {OUT_CHARS} of {len(text)} characters. "
                "Read on with sed -n 'a,bp' or narrow it with grep -n.]")
    return text


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
                        out, ok = run_bash(cmd, root, prof), True
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
