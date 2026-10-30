"""Разбор команды bash до запуска и подсказки к выводу — то, что видит модель помимо самого вывода.

Перенесено из стенда (researcher/fsr.py) без изменений логики. Песочница (agent.py) — граница безопасности;
здесь — что модель получает в ответ: понятный отказ («read-only, print to stdout», heredoc, find -exec,
«not allowed: X») вместо «Operation not permitted», заметки к пустому выводу и ошибкам, обрезка с указанием,
как дочитать.
"""

import os
import re
import shlex

ALLOWED = set()          # задаёт agent.py: программы + встроенные bash
PYTHON = True            # python3 в белом списке: heredoc python3 - <<'EOF'
WRITE_PROGS = {"tee", "cp", "mv", "rm", "rmdir", "mkdir", "touch", "ln", "dd", "install", "truncate", "chmod", "chown"}
BUILTINS = {"cd", "read", "break", "continue", ":", "[[", "pwd", "command"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "while", "until", "do", "done", "!", "{", "}"}
MAX_DEPTH = 100
MAX_CMD = 8000
FIND_BAD = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
OUT_CHARS = 8000
MAX_CAPTURE = 200_000
TOOLS = {}               # задаёт agent.py: другие инструменты сессии -> пример вызова ("" — без примера)


class _Deny(Exception):
    pass


READONLY_MSG = ("the directory is read-only and nothing can be written (no files, no /tmp); "
                "print results to stdout instead and narrow them with grep, head or sed -n")
HEREDOC_PY_MSG = ("here-documents (<<) work only as a whole command python3 - <<'EOF' ... EOF (a pipe like | head "
                  "may follow <<'EOF' on its first line); otherwise pass text with echo or printf through a pipe")
HEREDOC_RE = re.compile(r"\s*python3(?:[ \t]+-)?[ \t]*<<(-?)[ \t]*(['\"]?)([A-Za-z_]\w*)\2([^\n]*)\n")


def split_heredoc(cmd):
    """29.10 (PYTHON): python3 [-] <<[-]'EOF' [| ...]\n тело\nEOF -> ("python3 -[ | ...]", тело) или None.
    Тело идёт в stdin как есть (без подстановок, как при 'EOF'); после строки-ограничителя — ничего.
    Нет ограничителя — тело до конца (bash делает так же)."""
    m = HEREDOC_RE.match(cmd)
    if not m:
        return None
    tabs, word = m.group(1) == "-", m.group(3)
    lines = cmd[m.end():].split("\n")
    body = []
    for i, ln in enumerate(lines):
        x = ln.lstrip("\t") if tabs else ln
        if x.rstrip() == word:
            if "\n".join(lines[i + 1:]).strip():
                return None
            break
        body.append(x)
    return "python3 -" + m.group(4), "\n".join(body) + "\n"


NO_SUBST_MSG = ("command substitution inside ${...} or $((...)) is not supported; "
                "assign it to a variable first: v=$(...)")


def _cmd_pos(cur):
    """Начало простой команды: до сих пор в ней только ключевые слова (if, while, do, ! ...)."""
    return all(w in KEYWORDS for w in "".join(cur).split())


def _arith_end(s, i):
    """s[i:] начинается с '((' или '$((': -> индекс после '))'. Подстановку команды внутри не пускаем:
    v2 пропускал тело $((...)) не глядя, и $(( $(prog) )) обходил белый список."""
    j = s.find("))", i)
    if j < 0:
        raise _Deny("unbalanced $((")
    if "$(" in s[i + 2:j] or "`" in s[i + 2:j]:
        raise _Deny(NO_SUBST_MSG)
    return j + 2


def _scan(s, i, close, segs, meta=None, pipeamp=None, depth=0):
    """Разбор командной строки с кавычками. Режет на простые команды (segs); подстановки $(...), `...` и <(...)
    разбираются рекурсивно как отдельные команды, на их месте остаётся слово X. meta (v3): на каждую простую
    команду {piped: вход из пайпа, procsub: есть <(...), redir_in: есть '<'}. -> индекс после close.
    v3c: вложенность не глубже MAX_DEPTH (иначе RecursionError ронял харнесс)."""
    if depth > MAX_DEPTH:
        raise _Deny(f"command substitutions are nested more than {MAX_DEPTH} levels deep")
    cur = []
    st = {"piped": False, "procsub": False, "redir_in": False}
    dbl = False                                         # внутри [[ ... ]]: < > && || ( ) | — операторы теста

    def cut(piped_next=False):
        segs.append("".join(cur))
        if meta is not None:
            meta.append(dict(st))
        cur.clear()
        st.update(piped=piped_next, procsub=False, redir_in=False)

    while i < len(s):
        c = s[i]
        if close and not dbl and s.startswith(close, i):
            cut()
            return i + len(close)
        if c == "\\":
            cur.append(s[i:i + 2])
            i += 2
        elif c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise _Deny("unbalanced quotes")
            cur.append(s[i:j + 1])
            i = j + 1
        elif c == '"':
            i += 1
            buf = ['"']
            while True:
                if i >= len(s):
                    raise _Deny("unbalanced quotes")
                if s[i] == "\\":
                    buf.append(s[i:i + 2])
                    i += 2
                elif s[i] == '"':
                    buf.append('"')
                    i += 1
                    break
                elif s.startswith("$((", i):
                    i = _arith_end(s, i + 1)
                    buf.append("0")
                elif s.startswith("$(", i):
                    i = _scan(s, i + 2, ")", segs, meta, pipeamp, depth + 1)
                    buf.append("X")
                elif s[i] == "`":
                    i = _scan(s, i + 1, "`", segs, meta, pipeamp, depth + 1)
                    buf.append("X")
                else:
                    buf.append(s[i])
                    i += 1
            cur.append("".join(buf))
        elif s.startswith("$((", i):
            i = _arith_end(s, i + 1)
            cur.append("0")
        elif s.startswith("$(", i):
            i = _scan(s, i + 2, ")", segs, meta, pipeamp, depth + 1)
            cur.append("X")
        elif c == "`":
            i = _scan(s, i + 1, "`", segs, meta, pipeamp, depth + 1)
            cur.append("X")
        elif s.startswith("${", i):
            j = s.find("}", i)
            if j < 0:
                raise _Deny("unbalanced ${")
            if "$(" in s[i:j] or "`" in s[i:j]:             # v2 пропускал ${x:-$(prog)} не глядя
                raise _Deny(NO_SUBST_MSG)
            cur.append(s[i:j + 1])
            i = j + 1
        elif dbl and s.startswith("]]", i):
            dbl = False
            cur.append("]]")
            i += 2
        elif dbl and (s.startswith("&&", i) or s.startswith("||", i)):
            cur.append(s[i:i + 2])
            i += 2
        elif dbl and c in "<>()|":
            cur.append(c)
            i += 1
        elif s.startswith("[[", i) and _cmd_pos(cur) and s[i + 2:i + 3] in (" ", "\t", "\n"):
            dbl = True                                      # v3: [[ "$a" > "$b" ]] — сравнение, не запись
            cur.append("[[")
            i += 2
        elif s.startswith("((", i) and _cmd_pos(cur):
            i = _arith_end(s, i)                            # v3: (( n > 3 )) — арифметика, не запись
            cur.append(":")
        elif s.startswith("<<", i):
            raise _Deny(HEREDOC_PY_MSG if PYTHON else
                        "here-documents (<<) are not supported; pass text with echo or printf through a pipe")
        elif s.startswith("<(", i):
            i = _scan(s, i + 2, ")", segs, meta, pipeamp, depth + 1)   # v3: подстановка процесса — команда проверяется
            cur.append("X")
            st["procsub"] = True
        elif s.startswith(">(", i):
            raise _Deny("output process substitution >(...) is not supported; use a pipe")
        elif c in "<>" or s.startswith("&>", i):
            # номер дескриптора перед > (2>/dev/null) уже лежит в cur — убрать
            if cur and cur[-1].isdigit() and (len(cur) < 2 or cur[-2].isspace()):
                cur.pop()
            m = re.match(r"(&>>?|>>?&?|<&?)\s*([^\s|;&<>()]*)", s[i:])
            op, target = m.group(1), m.group(2)
            if op.startswith("<"):
                st["redir_in"] = True                       # чтение из файла: можно
            elif target == "/dev/null" or (op.endswith("&") and target.isdigit()) or op == ">&" and target.isdigit():
                pass
            elif op == ">" and target.startswith("&") and target[1:].isdigit():
                pass
            else:
                raise _Deny(f"'{op}{target}': {READONLY_MSG}")
            cur.append(" ")
            i += m.end()
        elif c == "#" and (i == 0 or s[i - 1] in " \t\n;|&("):
            j = s.find("\n", i)                             # комментарий оболочки — до конца строки
            i = len(s) if j < 0 else j
        elif s.startswith("&&", i) or s.startswith("||", i):
            cut()
            i += 2
        elif s.startswith("|&", i):                         # v3: |& = 2>&1 | (bash 3.2 его не знает — заменим)
            if pipeamp is not None:
                pipeamp.append(i)
            cut(True)
            i += 2
        elif c == "&":
            raise _Deny("background jobs ('&') are not allowed")
        elif c == "|":
            cut(True)
            i += 1
        elif c == "(":
            cut(st["piped"])                                # cmd | ( ... ): первая команда группы читает пайп
            i += 1
        elif c in ";\n)":
            cut()
            i += 1
        else:
            cur.append(c)
            i += 1
    if close:
        raise _Deny(f"unbalanced '{'$(' if close == ')' else close}'")
    if dbl:
        raise _Deny("unbalanced '[['")
    cut()
    return i


def _strip_kw(w):
    while w and (w[0] in KEYWORDS or re.match(r"^[A-Za-z_]\w*=", w[0])):
        w = w[1:]
    return w


def _awk_bad(prog):
    """Есть ли в программе awk system(), getline или вывод print/printf в файл/команду (> >> |).
    Сравнение вне print ($3 > "a", if (x > y)) — можно; строки и /регэкспы/ пропускаются."""
    i, n = 0, len(prog)
    depth, in_print, pdepth, prev = 0, False, 0, ""
    while i < n:
        c = prog[i]
        if c == '"' or (c == "/" and (prev == "" or prev in "(,~!{;&|?:\n")):
            j = i + 1
            while j < n and prog[j] != c:
                j += 2 if prog[j] == "\\" else 1
            i, prev = j + 1, c
            continue
        if c == "#":
            j = prog.find("\n", i)
            i = n if j < 0 else j
            continue
        if c.isalpha() or c == "_":
            word = re.match(r"[A-Za-z_]\w*", prog[i:]).group(0)
            if word in ("system", "getline"):
                return word
            if word in ("print", "printf"):
                in_print, pdepth = True, depth
            i += len(word)
            prev = "a"
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c in "{};\n":
            in_print = False
        elif c in ">|" and in_print and depth == pdepth:
            if prog[i:i + 2] == "||":
                i += 2
                prev = "|"
                continue
            return "redirect"
        if not c.isspace():
            prev = c
        i += 1
    return None


def _awk_check(w):
    i = 1
    while i < len(w):
        x = w[i]
        if x == "--":
            i += 1
            break
        if x.startswith("-f"):
            return "awk -f (program from a file) is not allowed; give the program inline"
        if x in ("-F", "-v"):
            i += 2
        elif x.startswith("-") and len(x) > 1:
            i += 1
        else:
            break
    if i < len(w) and _awk_bad(w[i]):
        return "awk may only read and print (no system(), getline, or print/printf output to files or commands with > or |)"
    return None


XARGS_VAL = set("EIJLnPRsS")        # ключи xargs BSD со значением


def _xargs_cmd(w):
    """xargs [ключи] [программа арг...] -> программа с аргументами (без программы xargs запускает echo)."""
    i = 1
    while i < len(w) and w[i].startswith("-") and len(w[i]) > 1:
        x = w[i]
        i += 1
        if x == "--":
            break
        for k, ch in enumerate(x[1:]):
            if ch in XARGS_VAL:
                if k == len(x) - 2:
                    i += 1                                  # значение — следующее слово (-I {} / -n 1)
                break
    return w[i:] or ["echo"]


def _check_words(w, m, via_xargs=False):
    p = w[0]
    if p in TOOLS:
        return (f"'{p}' is a separate tool, not a shell command: call the {p} tool directly instead of bash"
                + (", e.g. " + TOOLS[p] if TOOLS[p] else "") + ".")
    if p in WRITE_PROGS:
        return f"'{p}' writes files: {READONLY_MSG}"
    if p not in ALLOWED:
        return f"'{p}' is not allowed. Allowed programs: {', '.join(sorted(ALLOWED))}"
    if p == "command" and not (len(w) > 2 and w[1] in ("-v", "-V")):
        return "command works here only as command -v NAME (where a program is)"
    if via_xargs and (p in BUILTINS or p == "xargs"):
        return (f"xargs can only run a program from the list, not '{p}'; "
                "use a loop instead: ... | while read f; do ...; done")
    if p == "sed" and any(x.startswith("-i") or x.startswith("-I") or x.startswith("--in-place") for x in w[1:]):
        return f"sed -i is not allowed: {READONLY_MSG}"
    if p == "awk":
        return _awk_check(w)
    if p == "find" and FIND_BAD & set(w):
        return "find actions like -exec/-delete are not allowed; pipe the file list into grep, head, xargs or a for loop"
    if p == "sort" and any(x == "-o" or x.startswith("--output") or x.startswith("--compress") for x in w):
        return f"sort -o is not allowed: {READONLY_MSG}"
    if p == "diff" and (m.get("procsub") or m.get("piped") and "-" in w[1:]
                        or any(x in ("-", "/dev/stdin") or x.startswith("/dev/fd/") for x in w[1:])):
        return ("diff can only compare two files here (for piped input or <(...) it needs a temporary file, and "
                "nothing can be written). To compare command outputs use comm: comm -3 <(cmd1 | sort) <(cmd2 | sort)")
    if p == "xargs":
        return _check_words(_xargs_cmd(w), {}, via_xargs=True)
    return None


def check_command(cmd, parsed=None, pipeamp=None):
    """Проверка командной строки: каждая простая команда (в т.ч. внутри $(...), <(...), циклов, if/while и после
    xargs) — из белого списка. Безопасность держит sandbox-exec (запись, сеть, чтение вне вида); белый список не
    даёт запустить интерпретатор/eval. parsed (v3) <- [(слова, meta)] для подсказок. -> текст ошибки или None."""
    if "\x00" in cmd:
        return "the command contains a NUL byte (\\x00); shell commands cannot contain it"
    try:
        cmd.encode("utf-8")
    except UnicodeEncodeError:
        return "the command contains characters that are not valid UTF-8 (a lone surrogate); retype it"
    if len(cmd) > MAX_CMD:
        return f"the command is {len(cmd)} characters long; the limit is {MAX_CMD}. Split it into shorter commands"
    segs, meta = [], []
    try:
        _scan(cmd, 0, None, segs, meta, pipeamp)
    except _Deny as e:
        return str(e)
    for s, m in zip(segs, meta):
        try:
            w = _strip_kw(shlex.split(s))
        except ValueError as e:
            return f"cannot parse: {e}"
        if not w:
            continue
        if parsed is not None:
            parsed.append((w, m))
        if w[0] == "for":
            if len(w) < 3 or not re.fullmatch(r"[A-Za-z_]\w*", w[1]) or w[2] != "in":
                return "loops must look like: for f in logs/*; do head -n 3 \"$f\"; done"
            continue
        err = _check_words(w, m)
        if err:
            return err
    return None


# ---------------------------------------------------------------- исполнение


# ---------------------------------------------------------------- подсказки к выводу

STDIN_PROGS = {
    "cat": set(), "head": {"-n", "-c"}, "tail": {"-n", "-c"}, "wc": set(), "sort": {"-k", "-t", "-T", "-S"},
    "uniq": {"-f", "-s"}, "cut": {"-d", "-f", "-c", "-b"}, "nl": {"-b", "-d", "-f", "-h", "-i", "-l", "-n", "-s", "-v", "-w"},
    "rev": set(), "column": {"-c", "-s"}, "paste": {"-d"}, "od": {"-A", "-j", "-N", "-t"}, "xxd": {"-c", "-g", "-l", "-s", "-o"},
    "grep": {"-e", "-f", "-A", "-B", "-C", "-m", "-d", "-D", "--include", "--exclude", "--exclude-dir", "--context"},
    "sed": {"-e", "-f"}, "awk": {"-F", "-v", "-f"}, "tr": set(),
    "jq": {"--arg", "--argjson", "--rawfile", "--slurpfile", "-f", "--indent"},
}
XARGS_PIPE_RE = re.compile(r"^xargs: .*terminated with signal 13; aborting\n?", re.M)
NOFILE_EXAMPLE = {"grep": "grep -n PATTERN FILE (or grep -rn PATTERN DIR for a directory)", "sed": "sed -n '1,40p' FILE", "awk": "awk -F'|' '{print $1}' FILE"}


def _operands(w):
    """Файловые аргументы программы-фильтра (None — программа не читает stdin)."""
    p = w[0]
    vals = STDIN_PROGS.get(p)
    if vals is None:
        return None
    i, explicit = 1, False
    while i < len(w) and w[i].startswith("-") and w[i] != "-":
        x = w[i]
        i += 1
        if x == "--":
            break
        if p in ("grep", "sed") and re.fullmatch(r"-[a-zA-Z]*[ef]", x):
            explicit = True                                 # -e PATTERN / -f FILE: шаблон не позиционный
            i += 1
        elif p in ("grep", "sed") and re.match(r"-[ef].", x) or p == "awk" and x.startswith("-f"):
            explicit = True
            i += x == "-f"
        elif x in vals:
            i += 1
    rest = w[i:]
    if p in ("grep", "sed", "awk") and not explicit:
        rest = rest[1:]                                     # шаблон / скрипт / программа
    if p == "awk":
        rest = [r for r in rest if not re.match(r"^[A-Za-z_]\w*=", r)]
    if p == "tr":
        rest = []                                           # tr читает только stdin
    return rest


def _stdin_note(parsed, cmd, empty=True):
    """Фильтр не получил ни файла, ни пайпа (stdin тут пустой) -> заметка для модели. Нет файлового аргумента
    вовсе — заметка всегда (wc -l печатает 0 и без входа); аргумент-переменная — только при пустом выводе."""
    any_in = bool(re.search(r"<(?![(<])", cmd))
    for w, m in parsed:
        if m.get("piped") or m.get("redir_in"):
            continue
        p = w[0]
        if p == "read":
            if not any_in:
                return ("`read` got no input: nothing is piped into it and there is no other input here. "
                        "Pipe a list into the loop, e.g. ls logs | while read f; do ...; done")
            continue
        ops = _operands(w)
        if ops is None:
            continue
        if not ops or ops == ["-"]:
            return (f"`{p}` was given no file and nothing was piped into it, so it read nothing (input comes only "
                    f"from files and pipes here). Name the file, e.g. {NOFILE_EXAMPLE.get(p, p + ' FILE')}")
        var = [o for o in ops if re.fullmatch(r"\$\{?[A-Za-z_]\w*\}?|X", o)]
        if empty and var and len(var) == len(ops):
            v = var[0]
            name = re.sub(r"[${}]", "", v)
            if v != "X" and re.search(rf"\bfor\s+{name}\s+in\b", cmd):
                continue                                    # переменная цикла: пустой вывод = нет совпадений
            shown = "the $(...) result" if v == "X" else v
            return (f"if {shown} was empty, `{p}` got no file name and read nothing (there is no input here except "
                    f"files and pipes); check it, e.g. echo \"[{'$(...)' if v == 'X' else v}]\"")
    return None


NOFILE_RE = re.compile(r"([^\s:'\"]+): No such file or directory")
STEP_RE = re.compile(r"(\d+)\.(py|out)(\..+)?")


def _layout_notes(cmd, er, root):
    """«No such file» на logs/run_N.jsonl, которого нет в виде -> заметка, где список run."""
    notes = []
    for path in dict.fromkeys(NOFILE_RE.findall(er)):
        if re.search(r"(^|/)run_\d+\.jsonl$", path) and not os.path.isfile(os.path.join(root, path)):
            notes.append("logs/results.jsonl lists the runs in this directory.")
    return list(dict.fromkeys(notes))[:3]


BSD_NOTES = [
    (re.compile(r"grep: (?:invalid|unrecognized) option -- '?P"), "BSD grep has no -P; use grep -E (write [0-9] for \\d)."),
    (re.compile(r"find: -printf: unknown primary"), "BSD find has no -printf; print the paths and shorten them with "
                                                     "basename, dirname or sed."),
    (re.compile(r"head: illegal line count -- 0"), "BSD head needs a count of at least 1."),
    (re.compile(r"(?:illegal|invalid|unrecognized) option|unknown primary"),
     "these are macOS/BSD utilities; GNU-only options do not exist here."),
]


def _bsd_notes(er):
    for rx, note in BSD_NOTES:
        if rx.search(er):
            return [note]
    return []


COUNT_MAX = 10 * 2**20      # v3c: строки считаем не дальше 10 МБ


def _count_lines(path, limit=COUNT_MAX):
    """Строк в файле (как sed -n/grep -n: по \\n, хвост без \\n — строка). Читается кусками; файл больше limit
    байт -> None (не считаем: память и время не растут с размером)."""
    n, last, size = 0, b"", 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                return None
            n += chunk.count(b"\n")
            last = chunk[-1:]
    return n + (1 if size and last != b"\n" else 0)


def _file_map(cmd, root, parsed):
    """Команда — чтение одного файла (cat F, sed -n 'a,bp' F, head/tail -n N F; перед ней можно cd) ->
    (путь от корня вида, номер строки файла перед выводом, последняя строка диапазона, строк в файле)."""
    if not parsed or root is None or "|" in cmd or "$" in cmd.replace("$p'", "") or "`" in cmd:
        return None
    if any(m.get("piped") or m.get("procsub") for _, m in parsed):
        return None
    *cds, (w, _) = parsed
    base = root
    for cw, _ in cds:
        if cw[0] != "cd" or len(cw) != 2:
            return None
        base = os.path.normpath(os.path.join(base, cw[1].replace("~", root, 1)))
    p, f, off, end = w[0], None, 0, None
    if p == "cat" and len(w) == 2:
        f = w[1]
    elif p == "sed" and len(w) == 4 and w[1] == "-n":
        m = re.fullmatch(r"(\d+)(?:,(\d+|\$))?p", w[2])
        if m:
            f, off = w[3], int(m.group(1)) - 1
            end = int(m.group(2) or m.group(1)) if m.group(2) != "$" else None
    elif p in ("head", "tail"):
        a, n = w[1:], "10"
        if len(a) >= 2 and a[0] == "-n":
            n, a = a[1], a[2:]
        elif a and re.fullmatch(r"-n?\+?\d+", a[0]):
            n, a = a[0].lstrip("-n"), a[1:]
        if len(a) == 1 and re.fullmatch(r"\+?\d+", n):
            f = a[0]
            if p == "tail":
                off = int(n[1:]) - 1 if n.startswith("+") else None
                tail_n = int(n)
    if not f or f.startswith("-") or re.search(r"[*?\[{~]", f):
        return None
    full = os.path.normpath(os.path.join(base, f))
    if not full.startswith(root + "/") or not os.path.isfile(full):
        return None
    nl = _count_lines(full)
    if nl is None:
        return None                                     # v3c: файл больше COUNT_MAX — общая подсказка
    if off is None:
        off = max(0, nl - tail_n)
    end = min(end or nl, nl)
    return os.path.relpath(full, root), off, end, nl


def _pipe_hint(cmd, tail):
    c = (cmd or "").strip().rstrip(";").strip()
    if not c or "\n" in c or "#" in c or len(c) > 200:
        return f"run the same command again with `| {tail}` added at the end (wrap it as {{ ...; }} if it has several parts)"
    if re.search(r";|&&|\|\|", c):
        c = "{ " + c + "; }"
    return f"`{c} | {tail}`"


def clip(text, cmd=None, root=None, capped=False, parsed=None):
    """Обрезка вывода до OUT_CHARS. v3: подсказка «как дочитать» с номерами строк самого файла (одиночное чтение
    файла) или командой `<cmd> | sed -n 'a,bp'`; для строки длиннее OUT_CHARS — cut -c."""
    if len(text) <= OUT_CHARS and not capped:
        return text, False
    shown = text[:OUT_CHARS]
    k = shown.count("\n")
    if capped:
        total = f"more than {MAX_CAPTURE} bytes (the command was stopped there)"
    else:
        total = f"{len(text)} characters, {text.count(chr(10)) + (not text.endswith(chr(10)))} lines"
    fm = _file_map(cmd, root, parsed) if cmd else None
    c1, c2 = OUT_CHARS + 1, 2 * OUT_CHARS
    if k == 0:
        what = f"the first line alone is longer than {OUT_CHARS} characters"
        how = (f"`sed -n '{fm[1] + 1}p' {fm[0]} | cut -c {c1}-{c2}`" if fm
               else _pipe_hint(cmd, f"head -n 1 | cut -c {c1}-{c2}"))
    elif fm:
        rel, off, end, nl = fm
        a = off + k + 1
        b = max(a, min(end, a + 149))
        what = f"shown: lines {off + 1}-{off + k} of {rel}, which has {nl} lines"
        how = f"`sed -n '{a},{b}p' {rel}`"
    else:
        what = f"shown: lines 1-{k} of the output"
        how = _pipe_hint(cmd, f"sed -n '{k + 1},{k + 150}p'")
    return (shown + f"\n\n[output truncated: showing the first {OUT_CHARS} of {total}; {what}. "
            f"To read on: {how}. Or narrow it with grep -n.]"), True



