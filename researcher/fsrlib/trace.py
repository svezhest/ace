"""Учёт чтения трасс: какие logs/run_N.jsonl команда открыла. Только лог, модель не видит."""
import glob
import json
import os
import re

from . import check as K
from . import notes as N


# ---------------------------------------------------------------- учёт чтения трасс (только лог; модель не видит)

READ_PROGS = {"cat", "head", "tail", "sed", "nl", "awk", "grep", "cut", "sort", "uniq", "column", "paste", "rev",
              "od", "xxd", "jq", "diff", "comm"}       # показывают содержимое файла; ls, find, wc, test — нет
VAR_RE = re.compile(r"\$\{?([A-Za-z_]\w*)\}?")
ASSIGN_RE = re.compile(r"(?:^|[;&|\n(]|\bdo|\bthen)\s*([A-Za-z_]\w*)=(\"[^\"`]*\"|'[^']*'|[^\s;&|`()]*)(?=[\s;&|)]|$)")
STEP_FILE_RE = re.compile(r"^run_\d+\.jsonl$")      # view: файл run
MAX_COMBOS = 2000


def _braces(w):
    """Раскрытие {a,b} как в bash (вложенные — рекурсией); {} без запятой не трогается."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", w)
    if not m:
        return [w]
    out = []
    for alt in m.group(1).split(","):
        out += _braces(w[:m.start()] + alt + w[m.end():])
    return out


def _subst(word, env, wild=False):
    """Слово -> список слов с подставленными переменными цикла/присваивания; None — есть неизвестная переменная.
    wild: неизвестная переменная и $(...) (у разбора — X) -> glob '*' (какие файлы — неизвестно, run — по пути)."""
    for _ in range(3):                                  # присваивание со ссылкой на другую переменную: run="runs/$f"
        known = [n for n in dict.fromkeys(VAR_RE.findall(word)) if n in env and len(env[n]) == 1
                 and VAR_RE.search(env[n][0])]
        if not known:
            break
        for n in known:
            word = re.sub(r"\$\{?" + n + r"\b\}?", lambda _m, v=env[n][0]: v, word)
    def _split(m):                                      # разбор снимает кавычки: "$d"task.md -> $dtask.md
        n = m.group(1)
        if n in env or m.group(0).startswith("${"):
            return m.group(0)
        pre = max((v for v in env if n.startswith(v)), key=len, default=None)
        return "${" + pre + "}" + n[len(pre):] if pre else m.group(0)
    word = VAR_RE.sub(_split, word)
    names = list(dict.fromkeys(VAR_RE.findall(word)))
    if any(n not in env for n in names):
        if not wild:
            return None
        word = VAR_RE.sub(lambda m: m.group(0) if m.group(1) in env else "*", word)
        names = [n for n in names if n in env]
    words = [word]
    for n in names:
        rx = re.compile(r"\$\{?" + n + r"\b\}?")
        words = [rx.sub(lambda _m, v=v: v, x) for x in words for v in env[n]][:MAX_COMBOS]
    return words


def _expand(word, bases, root):
    """Слово-операнд -> существующие пути внутри вида (относительно корня): brace, glob, относительно cd."""
    out = []
    for b in bases:
        for w in _braces(word):
            full = os.path.normpath(os.path.join(b, w.replace("~", root, 1) if w.startswith("~") else w))
            hits = sorted(glob.glob(full)) if re.search(r"[*?\[]", w) else [full]
            for h in hits:
                h = os.path.normpath(h)
                if (h == root or h.startswith(root + "/")) and os.path.exists(h):
                    out.append(os.path.relpath(h, root) + ("/" if w.endswith("/") and h != root else ""))
    return list(dict.fromkeys(out))


def _run_of(rel):
    """view: путь от корня -> (номер run, имя файла) для logs/run_N.jsonl; 'logs' и '.' -> ('*', None)."""
    parts = [] if rel == "." else rel.rstrip("/").split("/")
    if not parts or parts == ["logs"]:
        return "*", None
    m = re.fullmatch(r"run_(\d+)\.jsonl", parts[-1]) if len(parts) == 2 and parts[0] == "logs" else None
    if m:
        return m.group(1), parts[-1]
    return None, None


def trace_reads(cmd, root, parsed):
    """Какие файлы трасс команда реально открыла программой, печатающей содержимое (cat/head/tail/sed/grep/awk/...),
    а не упомянула. Раскрываются cd, glob, {a,b}, переменные for и простые присваивания. Операнд, раскрывшийся в
    файлы одного run, — чтение этого run; операнд на несколько run (runs/*/..., grep -r по runs/ или .) — просмотр
    (scanned). grep -l/-L/-c/-q содержимого не показывает — не чтение. Операнд из stdin (xargs), $(...), read —
    unresolved. -> {"read": {run: [пути в run]}, "scanned": [run], "unresolved": [операнды]}."""
    read, scanned, unres = {}, set(), []
    if not parsed or root is None:
        return {"read": {}, "scanned": [], "unresolved": []}
    env = {}
    for m in ASSIGN_RE.finditer(cmd):
        if "$(" not in m.group(2):
            env[m.group(1)] = [m.group(2).strip("\"'")]
    try:
        all_runs = sorted(m.group(1) for f in os.listdir(os.path.join(root, "logs"))
                          for m in [re.fullmatch(r"run_(\d+)\.jsonl", f)] if m)
    except OSError:
        all_runs = []
    bases = [root]
    for w, meta in parsed:
        p = w[0]
        if p == "for" and len(w) >= 3 and w[2] == "in":
            vals, ok = [], True
            for x in w[3:]:
                s = _subst(x, env)
                if s is None or any("X" in y and not _expand(y, bases, root) for y in s):
                    ok = False
                    break
                for y in s:
                    exp = _expand(y, bases[:1], root) if bases and re.search(r"[*?\[{]", y) else []
                    # glob в списке for даёт пути от текущего каталога, как в bash
                    exp = [os.path.relpath(os.path.join(root, e), bases[0]) + ("/" if e.endswith("/") else "")
                           for e in exp]
                    vals += exp if exp else _braces(y)
            if ok:
                env[w[1]] = vals[:MAX_COMBOS]
            else:
                env.pop(w[1], None)
            continue
        if p == "read":
            for n in w[1:]:
                if not n.startswith("-"):
                    env.pop(n, None)
            continue
        if p == "cd":
            arg = w[1] if len(w) > 1 else root
            s = [y.replace("X", "*") for y in _subst(arg, env, wild=True)]
            nb = []
            for b in bases:
                for y in s:
                    for y2 in _braces(y):
                        full = os.path.normpath(os.path.join(b, y2.replace("~", root, 1) if y2.startswith("~") else y2))
                        nb += sorted(glob.glob(full)) if re.search(r"[*?\[]", y2) else [full]
            bases = list(dict.fromkeys(os.path.normpath(x) for x in nb if os.path.isdir(x)
                                       and (os.path.normpath(x) == root or x.startswith(root + "/"))))
            continue
        if p == "xargs":
            prog = fsr_xargs_prog(w)
            if prog in READ_PROGS:
                unres.append(" ".join(w)[:200])
            continue
        if p not in READ_PROGS:
            continue
        if p in ("diff", "comm"):
            ops = [x for x in w[1:] if not x.startswith("-")]
        else:
            ops = N._operands(w)
            if ops is None:
                ops = [x for x in w[1:] if not x.startswith("-")]
        flags = [x for x in w[1:] if x.startswith("-") and not x.startswith("--")]
        if p == "grep":
            if any(re.search(r"[lLcq]", x[1:]) for x in flags if re.fullmatch(r"-[a-zA-Z]+", x)) or any(
                    x in ("--files-with-matches", "--files-without-match", "--count", "--quiet") for x in w[1:]):
                continue
            recursive = any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", x) for x in flags) or "--recursive" in w
        else:
            recursive = False
        for o in ops:
            if o == "-":
                continue
            s = _subst(o, env)
            wild = s is None
            if wild:
                s = _subst(o, env, wild=True)
            if not bases:
                unres.append(o[:200])
                continue
            hits = []
            for y in s:
                h = _expand(y, bases, root)
                if not h and "X" in y:
                    h = _expand(y.replace("X", "*"), bases, root)
                    wild = wild or bool(h)
                hits += h
            if not hits:
                continue                                # нет такого файла: ничего не открыто
            runs, files = set(), []
            for h in hits:
                rid, inner = _run_of(h)
                full = os.path.join(root, h)
                if os.path.isdir(full):
                    if not recursive:
                        continue                        # cat/sed по каталогу ничего не читают
                    if rid == "*":
                        runs |= set(all_runs)
                        files.append(("*", None))
                    elif rid:
                        runs.add(rid)
                        files.append((rid, inner or ""))
                elif rid and rid != "*":
                    runs.add(rid)
                    files.append((rid, inner))
            if len(runs) == 1:
                rid = next(iter(runs))
                for r_, inner in files:
                    inner = (inner or "").rstrip("/")
                    if wild:
                        inner = "?" + inner                 # файл угадан по glob вместо переменной
                    read.setdefault(rid, [])
                    if inner not in read[rid]:
                        read[rid].append(inner)
            elif runs:
                scanned |= runs
    return {"read": {r: sorted(v) for r, v in sorted(read.items())}, "scanned": sorted(scanned - set(read)),
            "unresolved": list(dict.fromkeys(unres))}


def fsr_xargs_prog(w):
    try:
        return K._xargs_cmd(w)[0]
    except Exception:  # noqa: BLE001
        return None


def _is_trace_read(inner_files):
    """Run прочитан как трасса: открыт файл шага или каталог шагов/run (grep -r внутри run)."""
    return any(STEP_FILE_RE.match(f.lstrip("?")) for f in inner_files)


# ---------------------------------------------------------------- что модель увидела (по выводу, а не по команде)

SEEN_CHUNK = 60                  # знаков: кусок текста сообщения; он же окно поиска в выводе
_SEEN = {}                       # root -> {кусок: run}


def _unique_chunks(root):
    """Куски текста сообщений (как есть и в JSON-записи), которые встречаются только в одном run.
    Общее у всех run (промпт, демо) не считается."""
    if root in _SEEN:
        return _SEEN[root]
    owner = {}
    for f in glob.glob(os.path.join(root, "logs", "run_*.jsonl")):
        r = re.search(r"run_(\d+)\.jsonl$", f).group(1)
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                m = m.get("message") or {} if "event" in m else m
                parts = [m.get("content") or ""] + [str((c.get("function") or {}).get("arguments") or "")
                                                     for c in m.get("tool_calls") or []]
                for t in parts:
                    for form in (t, json.dumps(t, ensure_ascii=False)[1:-1]):
                        for k in range(0, len(form) - SEEN_CHUNK + 1, SEEN_CHUNK):
                            owner.setdefault(form[k:k + SEEN_CHUNK], set()).add(r)
    _SEEN[root] = {c: next(iter(rs)) for c, rs in owner.items() if len(rs) == 1}
    return _SEEN[root]


def seen_runs(text, root):
    """run -> куски его собственного текста, которые есть в выводе, полученном моделью (любым способом чтения)."""
    chunks = _unique_chunks(root)
    out = {}
    for i in range(len(text) - SEEN_CHUNK + 1):
        r = chunks.get(text[i:i + SEEN_CHUNK])
        if r:
            out.setdefault(r, set()).add(text[i:i + SEEN_CHUNK])
    return out


def seen_share(seen, root):
    """run -> доля (%) его собственного текста, которую модель получила (по накопленным кускам)."""
    total = {}
    for r in _unique_chunks(root).values():
        total[r] = total.get(r, 0) + 1
    return {r: round(100 * len(cs) / total[r], 1) for r, cs in sorted(seen.items(), key=lambda x: int(x[0]))}
