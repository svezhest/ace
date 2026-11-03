"""Ворота finish редактора: один раз по итогу всех правок — новые предупреждения pyflakes и падение smoke."""
import os

from .cfg import F
from . import cfg as C
from . import lint as LI

REVIEW_DIFF, REVIEW_RERUN = 5000, 2500   # --finish-review: символов diff и вывода rerun


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
    review = review_text(run) if C.FINISH_REVIEW and run.st["edits_applied"] else ""
    if not gate and not review:
        return "Finished.", True
    run.st["lint_at_finish"] = True
    if not review:
        return f"Not finished yet. {gate}\nFix them with edit, or call finish again to end as is.", False
    run.st["finish_review"] = True
    if run.final_left:
        run.final_left += 1                  # ход на ответ после показа
    return ("Not finished yet: here are your changes and what python3 tests/rerun.py prints on them."
            + (f"\n{gate}" if gate else "") + f"\n\n{review}\n\nIf this is the change you meant, call finish again; "
            "otherwise change it with edit."), False


def review_text(run):
    """--finish-review (4.11): все правки (diff от начала) и вывод python3 tests/rerun.py на них."""
    from . import work as WK
    d = WK.diff_src(C.BENCH, run.root)
    d = d if len(d) <= REVIEW_DIFF else d[:REVIEW_DIFF] + f"\n[... {len(d)} characters in all]"
    out = f"Your changes against the start:\n```diff\n{d.rstrip()}\n```"
    if os.path.exists(f"{run.root}/tests/rerun.py"):
        _, r, full, _, _ = F.bash_output("python3 tests/rerun.py", run.root, run.prof)
        r = full if len(full) <= REVIEW_RERUN else full[:REVIEW_RERUN] + f"\n[... {len(full)} characters in all]"
        out += f"\n\npython3 tests/rerun.py prints:\n{r.rstrip()}"
    return out
