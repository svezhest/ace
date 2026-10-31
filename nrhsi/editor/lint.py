"""pyflakes по правкам: новые предупреждения после edit и по итогу всех правок копии (pyflakes — из C.LINT или окружения)."""
import glob
import io
import os
import re
import sys

from . import cfg as C


def lint(text, rel):
    """pyflakes по тексту файла -> [(строка, сообщение)]."""
    if C.LINT:
        sys.path.insert(0, C.LINT)
    from pyflakes import api, reporter
    out = io.StringIO()
    api.check(text, rel, reporter.Reporter(out, out))
    res = []
    for ln in out.getvalue().splitlines():
        m = re.match(rf"{re.escape(rel)}:(\d+):(?:\d+:?)?\s*(.*)", ln)
        if m:
            res.append((int(m.group(1)), m.group(2)))
    return res


def lint_note(old, new, rel):
    """Предупреждения pyflakes, которых не было до правки (сравнение по тексту сообщения)."""
    if not rel.endswith(".py"):
        return ""
    before = {msg for _, msg in lint(old, rel)} if old else set()
    fresh = [(n, msg) for n, msg in lint(new, rel) if msg not in before]
    if not fresh:
        return ""
    return ("\npyflakes on " + rel + " after this change:\n" +
            "".join(f"  line {n}: {msg}\n" for n, msg in fresh[:10]))


def lint_changed(root):
    """Предупреждения pyflakes по изменённым .py копии root/src относительно исходного src вида (только новые)."""
    base, notes = f"{C.VIEWS[C.BENCH]}/src", ""
    for p in sorted(glob.glob(f"{root}/src/*.py")):
        rel = os.path.relpath(p, root)
        orig = f"{base}/{os.path.basename(p)}"
        old = open(orig).read() if os.path.exists(orig) else ""
        new = open(p).read()
        if new != old:
            notes += lint_note(old, new, rel)
    return notes.strip()
