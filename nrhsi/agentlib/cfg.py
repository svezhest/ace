"""Настройки цикла: пути, адрес модели, лимиты, белый список, схемы инструментов, строки промпта.
Функции других модулей читают их как C.ИМЯ в момент вызова (agent.ИМЯ = ... меняет их здесь)."""
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # nrhsi/: каталог agent.py
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
