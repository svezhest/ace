"""Разбор команды до запуска: белый список, запись, heredoc python3, тексты отказов."""
import re
import shlex

from . import cfg as C
from . import prompt as P


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
    return all(w in C.KEYWORDS for w in "".join(cur).split())


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
    if depth > C.MAX_DEPTH:
        raise _Deny(f"command substitutions are nested more than {C.MAX_DEPTH} levels deep")
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
            raise _Deny(HEREDOC_PY_MSG if C.PYTHON else
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
    while w and (w[0] in C.KEYWORDS or re.match(r"^[A-Za-z_]\w*=", w[0])):
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
    if p in ("report", "finish"):
        return (f"'{p}' is a separate tool, not a shell command: call the {p} tool directly instead of bash"
                + (", e.g. " + P.REPORT_EXAMPLE if p == "report" else "") + ".")
    if p in C.WRITE_PROGS:
        return f"'{p}' writes files: {READONLY_MSG}"
    if p not in C.ALLOWED:
        return f"'{p}' is not allowed. Allowed programs: {', '.join(sorted(C.ALLOWED))}"
    if p == "command" and not (len(w) > 2 and w[1] in ("-v", "-V")):
        return "command works here only as command -v NAME (where a program is)"
    if via_xargs and (p in C.BUILTINS or p == "xargs"):
        return (f"xargs can only run a program from the list, not '{p}'; "
                "use a loop instead: ... | while read f; do ...; done")
    if p == "sed" and any(x.startswith("-i") or x.startswith("-I") or x.startswith("--in-place") for x in w[1:]):
        return f"sed -i is not allowed: {READONLY_MSG}"
    if p == "awk":
        return _awk_check(w)
    if p == "find" and C.FIND_BAD & set(w):
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
    if len(cmd) > C.MAX_CMD:
        return f"the command is {len(cmd)} characters long; the limit is {C.MAX_CMD}. Split it into shorter commands"
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
