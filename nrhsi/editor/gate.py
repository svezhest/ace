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
    if C.TICKET:
        t += "\n\n" + ticket_check(run)
    return t


# ---------------------------------------------------------------- 6.11: проверка по тикету
# Ожидание ревьювера change_expected: prompt | control | any — в тикете (с --ticket-show его видит и писатель).
# prompt — меняется то, что модель читает (тексты .md в src/); control — меняется то, что делает код харнесса
# (видно, если вернуть тексты .md как в виде); any — что-то из двух. После каждой авто-проверки — Ok / Failed: причина.

def _replay(src, root, runs):
    cmd = [sys.executable, RERUN_CORE, "--bench", C.BENCH, "--src", src, "--logs", f"{root}/logs", "--json"] + [str(r) for r in runs]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        tail = [l for l in (p.stderr or p.stdout).strip().splitlines() if l.strip()]
        return {str(r): {"kind": "crash", "call": None, "text": tail[-1] if tail else ""} for r in runs}  # строка ошибки, не обрывок трассы


def _old_texts_src(run):
    """Копия src/ писателя, где все .md — как в виде (новые .md убраны): остаётся только код."""
    import shutil
    view = f"{C.VIEWS[C.BENCH]}/src"
    t = f"{C.HERE}/work/.ticket_{os.path.basename(run.root)}"
    shutil.rmtree(t, ignore_errors=True)
    shutil.copytree(f"{run.root}/src", t, ignore=shutil.ignore_patterns("__pycache__"))
    for d, _, fs in os.walk(t):
        for f in fs:
            if f.endswith(".md"):
                rel = os.path.relpath(os.path.join(d, f), t)
                if os.path.exists(f"{view}/{rel}"):
                    shutil.copy(f"{view}/{rel}", os.path.join(d, f))
                else:
                    os.remove(os.path.join(d, f))
    for d, _, fs in os.walk(view):
        for f in fs:
            rel = os.path.relpath(os.path.join(d, f), view)
            if f.endswith(".md") and not os.path.exists(f"{t}/{rel}"):
                os.makedirs(os.path.dirname(f"{t}/{rel}"), exist_ok=True)
                shutil.copy(os.path.join(d, f), f"{t}/{rel}")
    return t


def _texts_differ(run):
    view = f"{C.VIEWS[C.BENCH]}/src"
    a = {os.path.relpath(os.path.join(d, f), f"{run.root}/src"): open(os.path.join(d, f), errors="replace").read()
         for d, _, fs in os.walk(f"{run.root}/src") for f in fs if f.endswith(".md")}
    b = {os.path.relpath(os.path.join(d, f), view): open(os.path.join(d, f), errors="replace").read()
         for d, _, fs in os.walk(view) for f in fs if f.endswith(".md")}
    return a != b


def _where(d):
    if d["kind"] == "model" and d["call"] == 1:
        return "the prompt the model sees differs from the log from the start"
    at = "before the first model call" if d["call"] == 0 else f"from model call {d['call']} on"
    return f"it goes differently {at} ({d['text'][:120]})"


def ticket_check(run):
    exp, runs = C.TICKET["change_expected"], C.TICKET["runs"]
    cur = _replay(f"{run.root}/src", run.root, runs)
    texts = _texts_differ(run)
    code = _replay(_old_texts_src(run), run.root, runs) if texts else cur
    lines = []
    for r in runs:
        a, b = cur.get(str(r)), code.get(str(r))
        crash = next((d for d in (a, b) if d and d["kind"] == "crash"), None)
        if crash:
            lines.append(f"Failed: in run {r} the harness crashes" + (f" at model call {crash['call']}" if crash["call"] else "")
                         + f": {crash['text'].strip().splitlines()[0][:300] if crash['text'].strip() else 'no message'}")
            continue
        prompt_eff = texts and a is not None
        code_eff = b is not None
        if exp == "control":
            if code_eff:
                lines.append(f"Ok: in run {r} the harness now acts differently: {_where(b)}.")
            elif prompt_eff:
                lines.append(f"Failed: in run {r} only the texts the model reads have changed; with the old texts run {r} "
                             "goes exactly as in the log, to the end: the harness code does nothing different in it.")
            else:
                lines.append(f"Failed: run {r} goes exactly as in the log, to the end: this edit changes nothing in it.")
        elif exp == "prompt":
            if prompt_eff:
                lines.append(f"Ok: in run {r} the texts the model reads have changed: {_where(a)}.")
            elif code_eff:
                lines.append(f"Failed: in run {r} the texts the model reads are as before; only the harness code acts "
                             f"differently: {_where(b)}.")
            else:
                lines.append(f"Failed: run {r} goes exactly as in the log, to the end: this edit changes nothing in it.")
        else:
            if prompt_eff or code_eff:
                lines.append(f"Ok: run {r} changes: {_where(a or b)}.")
            else:
                lines.append(f"Failed: run {r} goes exactly as in the log, to the end: this edit changes nothing in it.")
    run.w({"type": "ticket_check", "expected": exp, "runs": runs, "cur": cur, "code": code, "lines": lines})
    return "Check against the observation:\n" + "\n".join(lines)
