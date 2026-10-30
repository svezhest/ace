"""Подсказки к выводу (stdin, нет файла, BSD) и обрезка вывода (clip)."""
import os
import re

from . import cfg as C


# ---------------------------------------------------------------- подсказки к выводу

# программы, читающие stdin, если файла нет; ключи со значением в следующем слове
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
    if len(text) <= C.OUT_CHARS and not capped:
        return text, False
    shown = text[:C.OUT_CHARS]
    k = shown.count("\n")
    if capped:
        total = f"more than {C.MAX_CAPTURE} bytes (the command was stopped there)"
    else:
        total = f"{len(text)} characters, {text.count(chr(10)) + (not text.endswith(chr(10)))} lines"
    fm = _file_map(cmd, root, parsed) if cmd else None
    c1, c2 = C.OUT_CHARS + 1, 2 * C.OUT_CHARS
    if k == 0:
        what = f"the first line alone is longer than {C.OUT_CHARS} characters"
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
    return (shown + f"\n\n[output truncated: showing the first {C.OUT_CHARS} of {total}; {what}. "
            f"To read on: {how}. Or narrow it with grep -n.]"), True
