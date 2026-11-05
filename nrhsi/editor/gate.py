"""Ворота finish редактора: один раз по итогу всех правок — новые предупреждения pyflakes и падение smoke."""
import json
import os
import re
import subprocess
import sys

from .cfg import F
from . import cfg as C
from . import lint as LI
from . import work as WK

REVIEW_DIFF, REVIEW_RERUN = 5000, 2500   # --finish-review: символов diff и вывода rerun


def smoke_failure(run):
    """31.10: правки без проверки — вывод python3 tests/smoke.py, если он упал (или '' — прошёл, нет теста)."""
    if not os.path.exists(f"{C.HIDDEN if C.HIDE_TOOLS else run.root + '/' + C.TOOLS_DIR}/smoke.py"):
        return ""
    ok, out, full = WK.tool_run(run, "smoke")
    return WK.tt("python3 tests/smoke.py now prints:\n") + out if not ok or "Traceback" in full else ""


def finish(run, args=None):
    """finish -> (текст для модели, конец ли). Шаг вариантов — конец сразу. Редактор: ворота pyflakes и smoke —
    один раз; --finish-review — обзор (все правки и rerun на них) при каждом finish после изменения src;
    finish(submit=false) — правки отбрасываются, src как в начале."""
    if run.role != "editor":
        return "Finished.", True
    from . import work as WK
    if C.FINISH_REVIEW and (args or {}).get("submit") in (False, "false", "False"):
        d = WK.diff_src(C.BENCH, run.root)
        run.w({"type": "dropped", "diff": d})
        WK.restore_src(C.BENCH, run.root)
        run.st["submitted"] = False
        return "Finished: nothing handed in; src/ is back to how it was at the start.", True
    h = WK.tree_hash(f"{run.root}/src")
    review = C.FINISH_REVIEW and run.st["edits_applied"] and h != run.st.get("reviewed_hash")
    if run.st.get("lint_at_finish") and not review:
        return "Finished.", True
    gate = "" if run.st.get("lint_at_finish") else LI.lint_changed(run.root)
    smoke = "" if run.st.get("lint_at_finish") else smoke_failure(run)
    if smoke:
        gate += ("\n" if gate else "") + smoke
    run.st["lint_at_finish"] = True
    if not review:
        if not gate:
            return "Finished.", True
        return f"Not finished yet. {gate}\nFix them with edit, or call finish again to end as is.", False
    run.st["reviewed_hash"] = h
    run.st["reviews"] = run.st.get("reviews", 0) + 1
    if run.final_left and run.st["reviews"] == 1:
        run.final_left += 1                  # ход на ответ после первого обзора
    return (f"Not handed in yet. Here are all your changes and what {rerun_name()} prints on them."
            + (f"\n{gate}" if gate else "") + f"\n\n{review_text(run)}\n\nIs this the change the observation "
            "needs? If it is, call finish again to hand it in. If not, change it with edit; or, if you think you "
            "could not make it, call finish with submit=false to hand in nothing."), False


def review_text(run):
    """--finish-review (4.11): все правки (diff от начала) и вывод python3 tests/rerun.py на них."""
    from . import work as WK
    d = WK.diff_src(C.BENCH, run.root)
    d = d if len(d) <= REVIEW_DIFF else d[:REVIEW_DIFF] + f"\n[... {len(d)} characters in all]"
    out = f"Your changes against the start:\n```diff\n{d.rstrip()}\n```"
    if C.RERUN:
        r = clip(rerun_output(run)[0], REVIEW_RERUN)
        out += f"\n\n{rerun_name()} prints:\n{r.rstrip()}"
    return out


def clip(t, n):
    return t if len(t) <= n else t[:n] + f"\n[... {len(t)} characters in all]"


def rerun_name():
    return "rerun" if C.RERUN_TOOL else WK.tt("python3 tests/rerun.py")


RERUN_CORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "editor", "rerun.py")


def rerun_output(run, n=None):
    """Вывод повтора прогонов на текущем src/ -> (текст, есть ли расхождение хоть в одном прогоне).
    --rerun-tool: ядро editor/rerun.py вне копии (в копии его нет), старый src — вид; иначе tests/rerun.py в песочнице."""
    if C.RERUN_TOOL:
        cmd = [sys.executable, RERUN_CORE, "--bench", C.BENCH, "--src", f"{run.root}/src", "--logs", f"{run.root}/logs",
               "--old", f"{C.VIEWS[C.BENCH]}/src"] + ([str(n)] if n is not None else [])
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        full = (p.stdout + p.stderr).strip()
    else:
        _, _, full = WK.tool_run(run, "rerun", f" {n}" if n is not None else "")
        full = full.strip()
    heads = [l for l in full.splitlines() if l and not l[0].isspace()]
    changed = any("no changes" not in l for l in heads)
    return clip(full, F.OUT_CHARS), changed


def type_name(x):
    return "nothing" if x is None else "array[str]" if isinstance(x, list) and any(isinstance(y, str) for y in x) else type(x).__name__


HEAD = re.compile(r"(all \d+ runs|runs? [\d, ]+) \(")


def changed_runs(full, root):
    """Строки-заголовки вывода rerun -> (изменившиеся прогоны, удачные, отличается ли промпт)."""
    res = [json.loads(l) for l in open(f"{root}/logs/results.jsonl")]
    every = [r["run"] for r in res]
    passed = {r["run"] for r in res if r.get("ok")}
    ch, prompt = set(), False
    for l in full.splitlines():
        if not l or l[0].isspace():
            continue
        m = HEAD.match(l)
        if not m:
            continue
        rs = every if m.group(1).startswith("all") else [int(x) for x in re.findall(r"\d+", m.group(1))]
        if "the prompt differs" in l:
            prompt = True
        elif "no changes" not in l:
            ch.update(rs)
    return ch, passed, prompt


def intent_report(run, expect):
    """--intent: ожидание правки (expect_runs) против прогонов, что изменились в повторе."""
    ch, passed, prompt = changed_runs(run.last_rerun or "", run.root)
    if prompt:
        return ("Your expectation: runs " + (", ".join(map(str, expect)) or "none") + ". The prompt differs from the "
                "log, so every run may go differently from the start; the replay cannot tell which runs change.")
    fmt = lambda rs: ", ".join(f"{r} (passed)" if r in passed else str(r) for r in sorted(rs)) or "none"
    ex = set(expect)
    return (f"Your expectation: runs {fmt(ex)}. Runs that changed: {fmt(ch)}. Changed but not expected: {fmt(ch - ex)}. "
            f"Expected but unchanged: {fmt(ex - ch)}.")


def ask_changed(run):
    """--ask-changed: удачные в логе прогоны, что после правки идут иначе -> вопрос (None, если таких нет или промпт другой)."""
    ch, passed, prompt = changed_runs(run.last_rerun or "", run.root)
    hit = sorted(ch & passed)
    if prompt or not hit:
        return None
    return (f"Runs that passed in the log and go differently now: {', '.join(map(str, hit))}. "
            "Is that what this edit is for?")


def edit_checks(run):
    """--auto-check (4.11): после применённой правки — новые предупреждения pyflakes, smoke, rerun; bash не тратится."""
    lint_ = LI.lint_changed(run.root)
    ok, out, full = WK.tool_run(run, "smoke")
    smoke = (WK.tt("python3 tests/smoke.py prints:\n") + out if not ok or "Traceback" in full else
             WK.tt("python3 tests/smoke.py runs without errors."))
    t = "Checks run on src/ after this edit (they use no bash calls):\n"
    if lint_:
        t += lint_ + "\n"
    if C.RERUN:
        full = rerun_output(run)[0]
        run.last_rerun = full
        t += smoke + f"\n{rerun_name()} prints:\n" + clip(full, REVIEW_RERUN).rstrip()
    else:
        t += smoke
    return t
