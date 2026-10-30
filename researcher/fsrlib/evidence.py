"""report: проверка evidence (strict / free); очистка текста модели от управляющих символов."""
import os
import re

from . import notes as N


# ---------------------------------------------------------------- report

EV_RE = re.compile(r"^\s*(?:\./)?([^:\s]+):L?(\d+)(?:\.\d+)?(?:\s*-\s*L?(\d+)(?:\.\d+)?)?(?:[:\s].*)?$", re.S)
EV_LIST_RE = re.compile(r"^\s*(?:\./)?([^:\s]+):(\d+(?:\s*,\s*\d+)+)\s*$")     # v3b: path:455,463,471
EV_TEXT_RE = re.compile(r"^\s*(?:\./)?([^\s:]+)\s*:\s+\D.*$", re.S)               # v3b: 'path: цитата'
RUN_FILE_RE = re.compile(r"(?!)")                                                  # view: исключения для файла run нет
EV_FILE_RE = re.compile(r"^\s*(?:\./)?([^:\s]+)\s*$")
WHOLE_FILE_MAX = 80


def check_evidence(ev, root):
    """-> (ошибки, нормализованные ссылки). Короткий файл можно сослать путём целиком (-> path:1-N)."""
    if not isinstance(ev, list) or not ev:
        return ["evidence must be a non-empty list of 'path:line' or 'path:start-end' strings"], []
    errs, norm = [], []
    items = []
    for e in ev:
        e = str(e)
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
        if not full.startswith(root + "/") or not os.path.isfile(full):
            errs.append(f"{e!r}: no such file '{path}'")
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
    if not isinstance(ev, list) or not [e for e in ev if str(e).strip()]:
        return ["evidence must be a non-empty list of strings"], []
    errs, norm = [], []
    for e in ev:
        e = str(e)
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
                errs.append(f"{e[:200]!r}: no such file or directory '{path}'")
                continue
        norm.append(e)
    return errs, norm


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
