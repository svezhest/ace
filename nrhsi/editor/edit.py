"""edit(path, old_string, new_string): одна замена в копии src/ -> текст для модели и запись в лог; отказ — с причиной."""
import os

from . import cfg as C
from . import lint as LI


class Refused(Exception):
    """Правка не применена: kind — вид отказа (st["edit_fail"]), msg — объяснение для модели."""

    def __init__(self, kind, msg):
        super().__init__(kind, msg)
        self.kind, self.msg = kind, msg


def numbered(lines, a, b):
    return "".join(f"{i + 1:>6}\t{lines[i]}" for i in range(a, b))


def mismatch(text, old):
    """Для отказа not_found: докуда old_string совпадает с файлом и что там в файле вместо остального."""
    lo, hi = 0, len(old)
    while lo < hi:                      # самое длинное начало old_string, которое есть в файле
        mid = (lo + hi + 1) // 2
        if old[:mid] in text:
            lo = mid
        else:
            hi = mid - 1
    if lo < 20:
        return " Even its beginning does not occur in the file."
    at = text.find(old[:lo])
    return (f" Its first {lo} characters match the file at line {text.count(chr(10), 0, at) + 1}; after them the file "
            f"has {text[at + lo:at + lo + 60]!r}, old_string has {old[lo:lo + 60]!r}.")


def locate(path, root, rec):
    """path модели -> (rel, полный путь, есть ли файл, его текст или None); только файлы src/, кроме bridge.py."""
    p = path.strip()
    if p.startswith(root + os.sep):
        p = os.path.relpath(p, root)
    rel = os.path.normpath(p)
    rec["rel"] = rel
    full = os.path.realpath(os.path.join(root, rel))
    srcd = os.path.join(root, "src")
    if not full.startswith(srcd + os.sep) or "__pycache__" in rel:
        raise Refused("path", f"{path} is not a file in src/; only files in src/ can be changed.")
    if os.path.relpath(full, srcd) == "bridge.py":
        raise Refused("bridge", "src/bridge.py is the connection to the benchmark, not part of the harness "
                                "(README.md); it cannot be changed.")
    exists = os.path.isfile(full)
    if os.path.exists(full) and not exists:
        raise Refused("path", f"{rel} is not a file.")
    text = open(full, encoding="utf-8").read() if exists else None
    return rel, full, exists, text


def replace(text, exists, old, new, rel, full):
    """-> (новый текст файла, строка начала замены, считая от 0)."""
    if old == "":
        if text:
            raise Refused("empty_old", f"old_string is empty, but {rel} is not empty; copy the text to replace from it.")
        if not exists and not os.path.isdir(os.path.dirname(full)):
            raise Refused("path", f"the directory of {rel} does not exist.")
        return new, 0
    if not exists:
        raise Refused("missing", f"{rel} does not exist.")
    n = text.count(old)
    if n == 0:
        raise Refused("not_found", f"old_string does not occur in {rel}; it must be copied exactly from the "
                                   "file's current text." + mismatch(text, old))
    if n > 1:
        starts, i = [], text.find(old)
        while i >= 0:
            starts.append(text.count("\n", 0, i) + 1)
            i = text.find(old, i + 1)
        raise Refused("multiple", f"old_string occurs {n} times in {rel} (starting at lines "
                                  f"{', '.join(map(str, starts[:10]))}); include more of the neighbouring text so "
                                  "that it occurs once.")
    i = text.find(old)
    return text[:i] + new + text[i + len(old):], text.count("\n", 0, i)


def check_syntax(newtext, rel, rec):
    if not rel.endswith(".py"):
        return
    try:
        compile(newtext, rel, "exec")
    except SyntaxError as e:
        rec["syntax"] = f"{e.msg} (line {e.lineno})"
        raise Refused("syntax", f"With this change {rel} would not parse as Python (SyntaxError: {e.msg}, line "
                                f"{e.lineno}); the file is unchanged.")


def write(full, newtext):
    tmp = full + ".edit_tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(newtext)
    os.replace(tmp, full)


def shown(newtext, new, a_line, rel, exists):
    """Ответ на применённую правку: что сделано и изменённые строки с соседними (номера строк, не больше SHOW_MAX)."""
    lines = newtext.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    b_line = a_line + max(1, new.count("\n") + (0 if new.endswith("\n") else 1)) if new else a_line
    lo, hi = max(0, a_line - C.SHOW_CONTEXT), min(len(lines), b_line + C.SHOW_CONTEXT)
    if hi - lo > C.SHOW_MAX:
        body = numbered(lines, lo, lo + C.SHOW_MAX) + f"[... {hi - lo - C.SHOW_MAX} more lines]\n"
    else:
        body = numbered(lines, lo, hi)
    what = (f"Applied: {rel} created." if not exists else
            f"Applied: {rel}, the new text is at lines {a_line + 1}-{max(a_line + 1, b_line)}." if new else
            f"Applied: text removed from {rel} at line {a_line + 1}.")
    return f"{what} Lines {lo + 1}-{hi} now read:\n{body}" if lines else f"{what} The file is now empty."


def do_edit(args, root, st):
    """-> (текст для модели, запись в лог). Применяет одну замену в root/src/..., либо объясняет отказ."""
    path, old, new = args.get("path"), args.get("old_string"), args.get("new_string")
    rec = {"path": path, "old": old, "new": new}
    try:
        if not isinstance(path, str) or not isinstance(old, str) or not isinstance(new, str):
            raise Refused("args", "path, old_string and new_string must all be strings.")
        rel, full, exists, text = locate(path, root, rec)
        if old == new:
            raise Refused("same", "old_string and new_string are the same, so there is nothing to change.")
        newtext, a_line = replace(text, exists, old, new, rel, full)
        check_syntax(newtext, rel, rec)
    except Refused as e:
        rec["fail"] = e.kind
        st["edit_fail"][e.kind] = st["edit_fail"].get(e.kind, 0) + 1
        return f"Error: edit not applied. {e.msg}", rec
    write(full, newtext)
    st["edits_applied"] += 1
    rec["applied"] = True
    rec["created"] = not exists
    note = LI.lint_note(text if exists else "", newtext, rel)
    rec["lint"] = note.strip() or None
    return shown(newtext, new, a_line, rel, exists) + note, rec
