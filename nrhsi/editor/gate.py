"""Ворота finish редактора: один раз по итогу всех правок — новые предупреждения pyflakes и падение smoke."""
import os

from .cfg import F
from . import lint as LI


def smoke_failure(run):
    """31.10: правки без проверки — вывод python3 tests/smoke.py, если он упал (или '' — прошёл, нет теста)."""
    if not os.path.exists(f"{run.root}/tests/smoke.py"):
        return ""
    ok, out, full, _, _ = F.bash_output("python3 tests/smoke.py", run.root, run.prof)
    return "python3 tests/smoke.py now prints:\n" + out if not ok or "Traceback" in full else ""


def finish(run):
    """finish -> (текст для модели, конец ли). Шаг вариантов и повторный finish редактора — конец сразу."""
    if run.role != "editor" or run.st.get("lint_at_finish"):
        return "Finished.", True
    gate = LI.lint_changed(run.root)
    smoke = smoke_failure(run)
    if smoke:
        gate += ("\n" if gate else "") + smoke
    if not gate:
        return "Finished.", True
    run.st["lint_at_finish"] = True
    return f"Not finished yet. {gate}\nFix them with edit, or call finish again to end as is.", False
