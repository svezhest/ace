"""report: проверка evidence (strict / free); очистка текста модели от управляющих символов."""
import difflib
import json
import os
import re

from . import cfg as C
from . import notes as N


# ---------------------------------------------------------------- report

EV_RE = re.compile(r"^\s*(?:\./)?([^:\s]+):L?(\d+)(?:\.\d+)?(?:\s*-\s*L?(\d+)(?:\.\d+)?)?(?:[:\s].*)?$", re.S)
EV_LIST_RE = re.compile(r"^\s*(?:\./)?([^:\s]+):(\d+(?:\s*,\s*\d+)+)\s*$")     # v3b: path:455,463,471
EV_TEXT_RE = re.compile(r"^\s*(?:\./)?([^\s:]+)\s*:\s+\D.*$", re.S)               # v3b: 'path: цитата'
RUN_FILE_RE = re.compile(r"(?!)")                                                  # view: исключения для файла run нет
EV_FILE_RE = re.compile(r"^\s*(?:\./)?([^:\s]+)\s*$")
WHOLE_FILE_MAX = 80


def _kind(x):
    return "None" if x is None else type(x).__name__


def shape_errors(ev):
    """31.10: evidence — массив строк. Строку не разбираем и не оборачиваем в список. -> ошибки (пусто — форма верна)."""
    if isinstance(ev, list):
        return [f"evidence[{i}]: expected type: str, got: {_kind(x)}" for i, x in enumerate(ev) if not isinstance(x, str)]
    if ev is None:
        return ["missing required argument: evidence (array[str])"]
    return [f"Expected type: array[str], got: {_kind(ev)}"]


GLOB_CH = re.compile(r"[*?\[]")


def _scratch(full, root):
    s = os.path.join(root, C.SCRATCH_DIR)
    return full == s or full.startswith(s + "/")


SIMILAR = 3


def missing(e, path, root):
    """Пути нет в виде -> 'No such file: P. Similar: ...' — до SIMILAR путей вида: сначала то же имя файла,
    потом похожие (difflib по пути)."""
    msg = f"{e[:200]!r}: No such file: {path}"
    if GLOB_CH.search(path):
        return msg + " (wildcards are not expanded)"
    allp = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not (d == root and x == C.SCRATCH_DIR))
        allp += [os.path.relpath(os.path.join(d, x), root) for x in sorted(files)]
    p = os.path.normpath(path.rstrip("/")).lstrip("./")
    base = os.path.basename(p)
    same = [x for x in allp if os.path.basename(x) == base]
    near = difflib.get_close_matches(p, [x for x in allp if x not in same], n=SIMILAR, cutoff=0.6)
    sim = (same + near)[:SIMILAR]
    return msg + (f". Similar: {', '.join(sim)}" if sim else "")


def scratch_msg(e, path):
    return f"{e[:200]!r}: {path} is in {C.SCRATCH_DIR}/ (written in this session), not a file of the repository"


def check_evidence(ev, root):
    """-> (ошибки, нормализованные ссылки). Короткий файл можно сослать путём целиком (-> path:1-N)."""
    bad = shape_errors(ev)
    if bad:
        return bad, []
    if not ev:
        return ["evidence must be a non-empty list of 'path:line' or 'path:start-end' strings"], []
    errs, norm = [], []
    items = []
    for e in ev:
        ml = EV_LIST_RE.match(e)
        items += [f"{ml.group(1)}:{x.strip()}" for x in ml.group(2).split(",")] if ml else [e]
    for e in items:
        if "\x00" in e:
            errs.append(f"{e!r}: contains a NUL byte (\\x00); give a plain 'path:line' reference")
            continue
        m = EV_RE.match(e)
        mf = None if m else (EV_FILE_RE.match(e) or EV_TEXT_RE.match(e))
        if not m and not mf:
            errs.append(f"{e!r}: expected 'path:line' or 'path:start-end'")
            continue
        path = (m or mf).group(1)
        full = os.path.realpath(os.path.join(root, path))
        if full.startswith(root + "/") and _scratch(full, root):
            errs.append(scratch_msg(e, path))
            continue
        if not full.startswith(root + "/") or not os.path.isfile(full):
            errs.append(missing(e, path, root) if not full.startswith(root + "/") or not os.path.exists(full)
                        else f"{e[:200]!r}: Is a directory: {path}")
            continue
        n = N._count_lines(full)                          # v3c: потоково (был построчный open: строка 1 ГБ — в память)
        if n is None:
            errs.append(f"{e!r}: '{path}' is too large to cite")
            continue
        if mf:
            if n > WHOLE_FILE_MAX and not RUN_FILE_RE.match(path):
                errs.append(f"{e!r}: '{path}' has {n} lines; cite the lines you mean, e.g. '{path}:12-30'")
                continue
            a, b = 1, max(1, n)
        else:
            a, b = int(m.group(2)), int(m.group(3) or m.group(2))
            if 1 <= a <= n < b:
                b = n                                           # v2.2: конец диапазона за концом файла -> до конца
            elif a > n and n <= WHOLE_FILE_MAX:
                a, b = 1, max(1, n)                             # v3b: начало за концом короткого файла -> целиком
        if not (1 <= a <= b <= max(1, n)):
            errs.append(f"{e!r}: '{path}' has {n} lines")
            continue
        norm.append(f"{path}:{a}" if a == b else f"{path}:{a}-{b}")
    return errs, norm


EV_HEAD_RE = re.compile(r"^\s*(?:\./)?([^\s:]+)(?::|\s*$)")     # A7: первое слово перед ':' (или единственное)
PATHLIKE_RE = re.compile(r"/|\.[A-Za-z]{1,6}$")                  # похоже на путь: есть '/' или расширение


def check_evidence_free(ev, root):
    """A7, EVIDENCE_MODE=free: непустой список строк в любой форме. Если элемент начинается с пути (path, path:...,
    'path: цитата'), путь должен существовать в виде (файл или каталог); номера строк и цитаты не проверяются.
    -> (ошибки, элементы как есть)."""
    bad = shape_errors(ev)
    if bad:
        return bad, []
    if not [e for e in ev if e.strip()]:
        return ["evidence must be a non-empty list of strings"], []
    errs, norm = [], []
    for e in ev:
        if not e.strip():
            continue
        if "\x00" in e:
            errs.append(f"{e[:200]!r}: contains a NUL byte (\\x00)")
            continue
        m = EV_HEAD_RE.match(e)
        path = m.group(1) if m else None
        if path and PATHLIKE_RE.search(path.rstrip("/")):
            full = os.path.realpath(os.path.join(root, path))
            if not (full == root or full.startswith(root + "/")) or not os.path.exists(full):
                errs.append(missing(e, path, root))
                continue
            if _scratch(full, root):
                errs.append(scratch_msg(e, path))
                continue
        norm.append(e)
    return errs, norm


# ---------------------------------------------------------------- источник цитированных строк лога

RUN_LOG_RE = re.compile(r"^logs/run_\d+\.jsonl$")
CITE_RE = re.compile(r"^\s*(?:\./)?([^:\s]+):(?:L?|\s*L?)(\d+)(?:\s*-\s*L?(\d+))?"
                     r"(?=\s*$|[:,;)]|\s+[-(—–:])")    # path:22, path:40-44, path: 40-44 (...); не 'path: 2023 was'

CITE_ITEMS = 6           # строк на элемент evidence
CITE_TOTAL = 15          # строк на весь ответ
QUOTE_MIN = 8


def line_kind(raw):
    """Строка лога -> её тип по собственным полям: 'event X, call Y' / 'role X' / 'type X'."""
    try:
        o = json.loads(raw)
    except ValueError:
        return "not JSON"
    if isinstance(o, dict):
        if isinstance(o.get("event"), str):
            c = o.get("call")
            return f"event {o['event']}" + (f", call {c}" if isinstance(c, str) else "")   # номер вызова — не тип
        for k in ("role", "type"):
            if isinstance(o.get(k), str):
                return f"{k} {o[k]}"
    return "JSON " + _kind(o)


def _strings(o, out):
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, dict):
        for v in o.values():
            _strings(v, out)
    elif isinstance(o, list):
        for v in o:
            _strings(v, out)
    return out


def _flat(t):
    return " ".join(t.split())


def _hay(raw):
    """Строка лога как есть и её строковые поля раскодированными (цитата бывает и в той, и в другой форме)."""
    try:
        dec = "\n".join(_strings(json.loads(raw), []))
    except ValueError:
        dec = ""
    return _flat(raw), _flat(dec)


def _quote_lines(q, lines):
    """Номера строк, где цитата есть целиком (части через ... / … — все, по порядку)."""
    parts = [_flat(x) for x in re.split(r"\.\.\.|…", q)]
    parts = [x for x in parts if len(x) >= 5] or [_flat(q)]
    out = []
    for i, raw in enumerate(lines, 1):
        for h in _hay(raw):
            j = 0
            for x in parts:
                j = h.find(x, j)
                if j < 0:
                    break
                j += len(x)
            if j >= 0:
                out.append(i)
                break
    return out


def _read_log(full):
    with open(full, encoding="utf-8", errors="replace", newline="") as f:
        ls = f.read().split("\n")
    if ls and ls[-1] == "":
        ls.pop()
    return ls


def cited_lines(items, root):
    """31.10: после принятого report — тип события каждой цитированной строки logs/run_N.jsonl (по полям самой
    строки); цитата без номера — строки, где она найдена. Только показ: на приём report не влияет. -> текст или ''."""
    rows, budget = [], CITE_TOTAL
    for e in items:
        if budget <= 0:
            rows.append("- (more items not listed)")
            break
        ml = EV_LIST_RE.match(e)
        m = None if ml else CITE_RE.match(e)
        mh = EV_HEAD_RE.match(e)
        path = (ml or m or mh).group(1) if (ml or m or mh) else None
        if not path or not RUN_LOG_RE.match(os.path.normpath(path)):
            continue
        full = os.path.realpath(os.path.join(root, path))
        if not full.startswith(root + "/") or not os.path.isfile(full):
            continue
        if N._count_lines(full) is None:
            continue
        lines = _read_log(full)
        n = len(lines)
        if ml or m:
            nums = ([int(x) for x in ml.group(2).split(",")] if ml else
                    list(range(int(m.group(2)), int(m.group(3) or m.group(2)) + 1)))
            ref = f"{path}:{ml.group(2).replace(' ', '') if ml else m.group(2) + ('-' + m.group(3) if m.group(3) else '')}"
            bad = [x for x in nums if not 1 <= x <= n]
            nums = [x for x in nums if 1 <= x <= n]
            if not nums:
                rows.append(f"- {ref} — the file has lines 1-{n}")
                continue
            shown = nums[:min(CITE_ITEMS, budget)]
            budget -= len(shown)
            body = ("by line: " if len(nums) > 1 else "") + " · ".join(
                (f"{x} {line_kind(lines[x - 1])}" if len(nums) > 1 else line_kind(lines[x - 1])) for x in shown)
            more = len(nums) - len(shown)
            rows.append(f"- {ref} — {body}" + (f" (+{more} more lines)" if more else "")
                        + (f"; the file has lines 1-{n}" if bad else ""))
            continue
        q = e[mh.end():].strip().strip("'\"`“”«»").strip()
        if len(q) < QUOTE_MIN:
            continue
        found = _quote_lines(q, lines)
        qs = repr(q[:40] + ("..." if len(q) > 40 else ""))
        if not found:
            continue                                    # не цитата дословно (или пересказ) — молчим
        shown = found[:min(CITE_ITEMS, budget)]
        budget -= len(shown)
        more = len(found) - len(shown)
        rows.append(f"- {path}: {qs} — found on line" + ("s " if len(found) > 1 else " ")
                    + ", ".join(f"{x} ({line_kind(lines[x - 1])})" for x in shown) + (f" (+{more} more lines)" if more else ""))
    if not rows:
        return ""
    return "Cited log lines, as the file has them:\n" + "\n".join(rows)


# ---------------------------------------------------------------- экспорт

# v3c: ESC-последовательности (CSI, OSC до BEL/ST, прочие ESC x) и управляющие C0/C1, кроме \n и \t
CTRL_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[ -~]?|[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def strip_controls(x):
    """Текст модели -> без управляющих символов (для экспорта и печати в терминал). Списки/словари — рекурсивно."""
    if isinstance(x, str):
        return CTRL_RE.sub("", x)
    if isinstance(x, list):
        return [strip_controls(v) for v in x]
    if isinstance(x, dict):
        return {k: strip_controls(v) for k, v in x.items()}
    return x
