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
    first = C.TICKET and getattr(C, "TICKET_FIRST", False)   # 6.11 --ticket-first: проверка по тикету — первой, до общего вывода
    if first:
        t += ticket_check(run) + "\n\n"
    if lint_:
        t += lint_ + "\n"
    if C.RERUN:
        full = rerun_output(run)[0]
        run.last_rerun = full
        t += smoke + f"\n{rerun_name()} prints:\n" + clip(full, REVIEW_RERUN).rstrip()
    else:
        t += smoke
    if C.TICKET and not first:
        t += "\n\n" + ticket_check(run)
    return t


# ---------------------------------------------------------------- 6.11: проверка по тикету
# Ожидание ревьювера change_expected: prompt | control | any — в тикете (с --ticket-show его видит и писатель).
# prompt — меняется то, что модель читает (тексты .md в src/); control — меняется то, что делает код харнесса
# (видно, если вернуть тексты .md как в виде); any — что-то из двух. После каждой авто-проверки — Ok / Failed: причина.

def _replay(src, root, runs, cover=False, watch=None):
    cmd = ([sys.executable, RERUN_CORE, "--bench", C.BENCH, "--src", src, "--logs", f"{root}/logs", "--json"]
           + (["--cover"] if cover else []) + (["--watch", json.dumps(watch)] if watch else []) + [str(r) for r in runs])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
        return (out["div"], out["cover"]) if cover else out
    except Exception:  # noqa: BLE001
        tail = [l for l in (p.stderr or p.stdout).strip().splitlines() if l.strip()]
        div = {str(r): {"kind": "crash", "call": None, "text": tail[-1] if tail else ""} for r in runs}  # строка ошибки, не обрывок трассы
        return (div, {}) if cover else div


def _changed_lines(run):
    """{файл .py в src: [номера изменённых или новых строк, которые исполняет код функций]} против вида.
    Строки уровня модуля (def, импорт, константы) выполняются при импорте, до проигрыша, — их не считаем."""
    import difflib
    view = f"{C.VIEWS[C.BENCH]}/src"
    out = {}
    for d, _, fs in os.walk(f"{run.root}/src"):
        for f in fs:
            if not f.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(d, f), f"{run.root}/src")
            new = open(os.path.join(d, f), errors="replace").read().splitlines()
            old = open(f"{view}/{rel}", errors="replace").read().splitlines() if os.path.exists(f"{view}/{rel}") else []
            ch = set()
            for op, _, _, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
                if op in ("replace", "insert"):
                    ch.update(range(j1 + 1, j2 + 1))
            if not ch:
                continue
            try:
                top = compile("\n".join(new) + "\n", rel, "exec")
            except SyntaxError:
                continue
            exe, stack = set(), [c for c in top.co_consts if hasattr(c, "co_lines")]
            while stack:
                c = stack.pop()
                exe.update(l for _, _, l in c.co_lines() if l and (l != c.co_firstlineno or c.co_name.startswith("<")))  # строка def — не выполнение
                stack += [k for k in c.co_consts if hasattr(k, "co_lines")]
            lines = sorted(ch & exe)
            if lines:
                out[rel] = (lines, new)
    return out


_SAFE_CALLS = {"len", "set", "list", "tuple", "sorted", "str", "int", "bool", "any", "all", "min", "max", "repr",
               "get", "strip", "lower", "upper", "split", "startswith", "endswith", "count", "index", "keys", "values", "items"}


def _safe(n):
    """Выражение без побочных эффектов: вызовы — только чистые встроенные и методы строк/словарей или функции по имени."""
    import ast
    for c in ast.walk(n):
        if isinstance(c, (ast.NamedExpr, ast.Lambda, ast.Await, ast.Yield, ast.YieldFrom)):
            return False
        if isinstance(c, ast.Call):
            f = c.func
            if isinstance(f, ast.Attribute) and f.attr not in _SAFE_CALLS:
                return False   # методы вроде execute, send, append, pop — не вычисляем
            if isinstance(f, ast.Name) and f.id in ("print", "exec", "eval", "open", "input", "llm", "call_hook", "setattr"):
                return False
            if not isinstance(f, (ast.Name, ast.Attribute)):
                return False
    return True


def _operands(cond):
    """Выражения-операнды условия (сравнения, `not`, and/or разбираются), которые можно вычислить без побочных эффектов:
    вызовы — только чистые встроенные и методы строк/словарей, либо функции src без аргументов-вызовов."""
    import ast
    try:
        tree = ast.parse(cond, mode="eval").body
    except SyntaxError:
        return []
    out = []
    safe = _safe

    def walk(n):
        if isinstance(n, ast.BoolOp):
            for v in n.values:
                walk(v)
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            walk(n.operand)
        elif isinstance(n, ast.Compare):
            for v in [n.left] + n.comparators:
                walk(v)
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("all", "any")
              and n.args and isinstance(n.args[0], (ast.GeneratorExp, ast.ListComp))):
            walk(n.args[0].generators[0].iter)   # all/any(… for x in X): значение целиком — то же «never true», смотрим на X
        elif not isinstance(n, ast.Constant) and safe(n):
            out.append(ast.unparse(n))
    walk(tree)
    return list(dict.fromkeys(out))[:4]


def _cond_of(text, ln):
    """Текст условия строки if/elif/while (многострочного — до двоеточия) или выражения return."""
    src = text[ln - 1].strip()
    if src.startswith("return "):
        return src.split("  #")[0][7:].strip()
    end = next((k for k in range(ln, min(ln + 8, len(text)) + 1) if text[k - 1].split("#")[0].rstrip().endswith(":")), None)
    if end is None:
        return None
    body = " ".join(t.split("#")[0].strip().rstrip("\\").strip() for t in text[ln - 1:end])
    for kw in ("if ", "elif ", "while "):
        if body.startswith(kw):
            return body[len(kw):].rstrip().rstrip(":").strip()
    return None


def _watch(changed):
    w = {}
    for rel, (lines, text) in changed.items():
        for ln in lines:
            src = text[ln - 1].strip()
            if src.startswith(("if ", "elif ", "while ", "return ")):
                c = _cond_of(text, ln)
                ops = _operands(c) if c else []
                if ops:
                    w[f"{rel}:{ln}"] = ops
    return w


def _dead_fact(changed, cov, hide=frozenset()):
    """Одна фраза для строки Failed (6.11 --ticket-line): до двух изменённых условий, которые выполнялись и ни разу
    не были истинны (`if` без выполненного тела; `return <выражение>` с одним и тем же значением), чаще выполнявшиеся — первыми;
    или «ни одна изменённая строка не выполнялась». `return False` и подобные литералы не в счёт: они постоянны по построению."""
    ret = cov.get("__ret__") or {}
    any_ran, cand, dead = False, [], None
    for rel, (lines, text) in sorted(changed.items()):
        hits = {int(k): v for k, v in (cov.get(rel) or {}).items()}
        rets = {int(k): v for k, v in (ret.get(rel) or {}).items()}
        for ln in lines:
            n, src = hits.get(ln, 0), text[ln - 1].strip()
            code = src.split("  #")[0].split(" # ")[0].strip()
            if not n and any_ran and not dead and not code.startswith(("else", "elif", "except", "finally")):
                dead = (ln, rel, code)   # первая изменённая строка, не выполнявшаяся после выполнявшейся
            any_ran = any_ran or n > 0
            if not n:
                continue
            if src.startswith(("if ", "elif ", "while ")):
                end = next((k for k in range(ln, min(ln + 8, len(text)) + 1) if text[k - 1].split("#")[0].rstrip().endswith(":")), None)
                if end is None:
                    continue
                ind = len(text[ln - 1]) - len(text[ln - 1].lstrip())
                body = next((k for k in range(end + 1, len(text) + 1) if text[k - 1].strip() and not text[k - 1].strip().startswith("#")), None)
                if body and len(text[body - 1]) - len(text[body - 1].lstrip()) > ind and hits.get(body, 0) == 0:
                    cand.append((n, f"`{src[:80]}` at src/{rel}:{ln} ran {n} times and was never true", f"{rel}:{ln}"))
            elif code.startswith("return ") and code[7:].strip() not in ("False", "True", "None", "{}", "[]", "0", "1", '""') \
                    and len(rets.get(ln) or {}) == 1 and next(iter(rets[ln])) in ("False", "None", "True"):
                cand.append((n, f"`{src[:80]}` at src/{rel}:{ln} ran {n} times and returned {next(iter(rets[ln]))} every time", f"{rel}:{ln}"))
    if cand:
        cand.sort(key=lambda c: -c[0])
        def with_vals(c):
            val = (cov.get("__val__") or {}).get(c[2]) if getattr(C, "TICKET_VALUES", False) else None
            # ошибка вычисления операнда — обычно это короткое замыкание (`out and out.get(...)` при out = None):
            # такой операнд условие не вычисляло, показывать его нельзя
            vals = {e: v for e, v in ((val or {}).get("vals") or {}).items() if e not in hide
                    and not (isinstance(v, str) and v.startswith("<") and v.endswith(">") and ("Error" in v or "Exception" in v))}
            if not vals:
                return c[1]
            return (c[1] + f" (at its last run, before model call {val['call'] + 1}: "
                    + ", ".join(f"`{e}` = {v}" for e, v in vals.items()) + ")")
        return "your " + "; your ".join(with_vals(c) for c in cand[:2])
    if dead:
        return f"your `{dead[2][:80]}` at src/{dead[1]}:{dead[0]} never ran"
    return None if any_ran else "none of the lines you changed ran in it"


def _key_probes(changed):
    """6.11 --ticket-why: `X.get("k")` в изменённых строках -> {"файл:строка": {проба: (X, k)}}.
    Проба вычисляется в начале строки: список ключей X, если "k" в нём нет, иначе None."""
    import ast
    out = {}
    for rel, (lines, text) in changed.items():
        try:
            tree = ast.parse("\n".join(text) + "\n")
        except SyntaxError:
            continue
        want = set(lines)
        for st in ast.walk(tree):
            if not isinstance(st, ast.stmt) or st.lineno not in want:
                continue
            parts = ([st.test] if isinstance(st, (ast.If, ast.While)) else [st.iter] if isinstance(st, ast.For) else
                     [] if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.With, ast.Try)) else [st])
            for part in parts:
                for c in ast.walk(part):
                    if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "get" and c.args
                            and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str)
                            and all(isinstance(n, (ast.Name, ast.Attribute, ast.Load)) for n in ast.walk(c.func.value))):
                        b, k = ast.unparse(c.func.value), c.args[0].value
                        probe = f"(', '.join(sorted(map(str, {b}))) if {k!r} not in {b} else None)"
                        out.setdefault(f"{rel}:{st.lineno}", {})[probe] = (b, k)
    return out


def _shadowed(changed):
    """6.11 --ticket-why: изменённые строки внутри def, который ниже в том же модуле или классе перекрыт def с тем же именем
    -> [(файл, имя, строка своего def, строка последнего def, строки своего тела)]."""
    import ast
    out = []
    for rel, (lines, text) in changed.items():
        try:
            tree = ast.parse("\n".join(text) + "\n")
        except SyntaxError:
            continue
        for body in [tree.body] + [n.body for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            defs = [n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for i, d in enumerate(defs):
                later = [e for e in defs[i + 1:] if e.name == d.name]
                mine = [ln for ln in lines if d.lineno <= ln <= d.end_lineno]
                if later and mine:
                    out.append((rel, d.name, d.lineno, later[-1], mine))
    return out


def _why_fact(changed, cov, probes, r):
    """Почему изменённое не действует: перекрытый def; `X.get("k")` при отсутствии ключа "k" в X. Только факты прогона."""
    import ast
    res = []
    for rel, name, l1, later, mine in _shadowed(changed):
        hits = {int(k): v for k, v in (cov.get(rel) or {}).items()}
        if any(hits.get(ln, 0) for ln in mine):
            continue
        body = later.body[0].lineno if later.body else later.lineno
        if body and later.body and isinstance(later.body[0], ast.Expr) and len(later.body) > 1:
            body = later.body[1].lineno   # docstring не выполняется как строка
        n = hits.get(body, 0)
        res.append(f"src/{rel} defines `{name}` again at line {later.lineno}, below yours at line {l1}, and the later "
                   f"definition is the one in use" + (f" (it ran {n} times in run {r})" if n else ""))
    vals = cov.get("__val__") or {}
    for where, ps in probes.items():
        got = (vals.get(where) or {}).get("vals") or {}
        for probe, (b, k) in ps.items():
            v = got.get(probe)
            if not v or v == "None" or (v.startswith("<") and v.endswith(">")):
                continue
            keys = v[1:-1] if v[:1] in "'\"" and v[-1:] == v[:1] else v
            res.append(f"at src/{where} `{b}` has no key {k!r} (its keys: {keys})")
            break
    return res[:2]


def _cond_probes(changed):
    """6.11 --ticket-passed: {"файл:строка": проба} — значение самого изменённого условия (если вычислимо без побочных эффектов)."""
    import ast
    out = {}
    for rel, (lines, text) in changed.items():
        for ln in lines:
            if text[ln - 1].strip().startswith(("if ", "elif ", "while ")):
                c = _cond_of(text, ln)
                try:
                    ok = c and _safe(ast.parse(c, mode="eval"))
                except SyntaxError:
                    ok = False
                if ok:
                    out[f"{rel}:{ln}"] = f"bool({c})"
    return out


def _fired_fact(changed, cov, hide=frozenset(), cprobe=None):
    """6.11 --ticket-passed: изменённые условия, тело которых выполнялось в прогоне (до расхождения) и которые истинны на последнем
    выполнении (если это вычислимо), и `return <выражение>`, вернувшие True, — до двух, со значениями операндов."""
    res = []
    vals = cov.get("__val__") or {}
    ret = cov.get("__ret__") or {}
    tm = lambda n: f"{n} time" + ("" if n == 1 else "s")
    for rel, (lines, text) in sorted(changed.items()):
        hits = {int(k): v for k, v in (cov.get(rel) or {}).items()}
        rets = {int(k): v for k, v in (ret.get(rel) or {}).items()}
        for ln in lines:
            src = text[ln - 1].strip()
            code = src.split("  #")[0].split(" # ")[0].strip()
            if hits.get(ln) and code.startswith("return ") and code[7:].strip() not in ("False", "True", "None") \
                    and (rets.get(ln) or {}).get("True"):
                res.append((rets[ln]["True"], f"your `{src[:80]}` at src/{rel}:{ln} returned True {tm(rets[ln]['True'])}"))
                continue
            if not hits.get(ln) or not src.startswith(("if ", "elif ", "while ")):
                continue
            pv = ((vals.get(f"{rel}:{ln}") or {}).get("vals") or {}).get((cprobe or {}).get(f"{rel}:{ln}"))
            if pv == "False":   # на последнем выполнении ложно: это охрана, не то, что сработало
                continue
            end = next((k for k in range(ln, min(ln + 8, len(text)) + 1) if text[k - 1].split("#")[0].rstrip().endswith(":")), None)
            if end is None:
                continue
            ind = len(text[ln - 1]) - len(text[ln - 1].lstrip())
            body = next((k for k in range(end + 1, len(text) + 1) if text[k - 1].strip() and not text[k - 1].strip().startswith("#")), None)
            if not body or len(text[body - 1]) - len(text[body - 1].lstrip()) <= ind or not hits.get(body):
                continue
            v = vals.get(f"{rel}:{ln}") or {}
            ops = {e: x for e, x in (v.get("vals") or {}).items() if e not in hide
                   and not (isinstance(x, str) and x.startswith("<") and x.endswith(">") and ("Error" in x or "Exception" in x))}
            res.append((hits[body], f"your `{src[:80]}` at src/{rel}:{ln} was true {tm(hits[body])}"
                       + (f" (at its last run, before model call {v['call'] + 1}: " + ", ".join(f"`{e}` = {x}" for e, x in ops.items()) + ")"
                          if ops else "")))
    # то, после чего прогон разошёлся, обычно сработало раз-другой; охраны вроде `if history:` — на каждом шаге
    return [t for _, t in sorted(res, key=lambda x: x[0])[:2]]


def passed_fact(run, changed, watch, hide):
    """6.11 --ticket-passed: первый удачный в логе прогон (не из тикета), который с кодом правки (тексты — как в виде) идёт иначе:
    где он расходится и какие изменённые условия в нём сработали. None — такого нет или промпт отличается от лога."""
    ch, passed, prompt = changed_runs(run.last_rerun or "", run.root)
    hit = sorted((ch & passed) - set(C.TICKET["runs"]))
    if prompt or not hit or not changed:
        return None
    r = hit[0]
    src = _old_texts_src(run) if _texts_differ(run) else f"{run.root}/src"
    cp = _cond_probes(changed)
    w = {k: list(v) if isinstance(v, list) else v for k, v in (watch or {}).items()}
    for where, pr in cp.items():
        w.setdefault(where, []).append(pr)
    div, cov = _replay(src, run.root, [r], cover=True, watch=w or None)
    d = div.get(str(r))
    if not d or d["kind"] == "crash":
        return None
    f = _fired_fact(changed, cov.get(str(r)) or {}, hide | set(cp.values()), cp)
    more = f" (of {len(hit)} such runs: {', '.join(map(str, hit[:8]))}{' …' if len(hit) > 8 else ''})" if len(hit) > 1 else ""
    return (f"Run {r} passed in the log{more}; with your code it goes differently from model call {d['call']} on"
            + (": " + "; ".join(f) if f else "") + ".")


def _cover_lines(changed, cov, d):
    """Строки правки со счётчиками в одном прогоне: подряд идущие с одним счётчиком — одной строкой."""
    upto = ("to the end of the log" if d is None else
            "up to model call %s, where it goes differently" % d["call"] if d.get("call") else "until it stops")
    res = []
    ret = (cov.get("__ret__") or {}) if getattr(C, "TICKET_RET", False) else {}
    for rel, (lines, text) in sorted(changed.items()):
        hits = {int(k): v for k, v in (cov.get(rel) or {}).items()}
        rets = {int(k): v for k, v in (ret.get(rel) or {}).items()}
        groups = []
        for ln in lines:
            n = hits.get(ln, 0)
            if groups and groups[-1][2] == n and not rets.get(ln) and not rets.get(groups[-1][1]) and groups[-1][1] == ln - 1 - sum(1 for k in range(groups[-1][1] + 1, ln) if k in lines):
                groups[-1][1] = ln
            else:
                groups.append([ln, ln, n])
        for a, b, n in groups:
            where = f"src/{rel}:{a}" + (f"-{b}" if b != a else "")
            rv = rets.get(b) if text[b - 1].strip().startswith("return") else None
            got = (" -> returned " + ", ".join(f"{k} {'once' if m == 1 else f'{m} times'}" for k, m in sorted(rv.items(), key=lambda kv: -kv[1])[:3])) if rv else ""
            res.append(f"  {where}  {'never ran' if n == 0 else 'ran once' if n == 1 else f'ran {n} times'}:  {text[a - 1].strip()[:90]}{got}")
    if len(res) > 14:
        res = res[:13] + [f"  ... {len(res) - 13} more groups of changed lines"]
    return upto, res


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
    cover = getattr(C, "TICKET_COVER", False)
    tline = getattr(C, "TICKET_LINE", False)
    changed = _changed_lines(run) if cover or tline else {}
    watch = _watch(changed) if tline and getattr(C, "TICKET_VALUES", False) else None
    why = watch is not None and getattr(C, "TICKET_WHY", False)
    probes = _key_probes(changed) if why else {}
    if why:   # 6.11 --ticket-why: пробы ключей — в те же строки наблюдения; длинные строки — с размером
        for where, ps in probes.items():
            watch.setdefault(where, []).extend(ps)
        watch["__shape__"] = True
        if getattr(C, "TICKET_PASSED", False):
            watch["__shape2__"] = True
    hide = frozenset(p for ps in probes.values() for p in ps)
    cur, cov = (_replay(f"{run.root}/src", run.root, runs, cover=True, watch=watch) if cover or tline
                else (_replay(f"{run.root}/src", run.root, runs), {}))
    texts = _texts_differ(run)
    code, cov_code = ((_replay(_old_texts_src(run), run.root, runs, cover=True, watch=watch) if why
                       else (_replay(_old_texts_src(run), run.root, runs), {})) if texts else (cur, cov))
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
    if tline and changed:   # самый важный факт покрытия — в саму строку Failed «как в логе»
        for i, r in enumerate(runs):
            if lines[i].startswith(f"Failed: run {r} goes exactly as in the log"):
                c = cov.get(str(r)) or {}
            elif why and lines[i].startswith(f"Failed: in run {r} only the texts the model reads have changed"):
                c = cov_code.get(str(r)) or {}   # код без новых текстов идёт как в логе — факт о нём
            else:
                continue
            f = [x for x in [_dead_fact(changed, c, hide)] if x] + (_why_fact(changed, c, probes, r) if why else [])
            if f:
                lines[i] = lines[i].rstrip(".") + f"; in run {r} " + "; ".join(f) + "."
    if cover and changed:   # по одной строке на прогон — после каждой её счётчики
        assert len(lines) == len(runs)
        out = []
        for r, ln in zip(runs, lines):
            out.append(ln)
            a = cur.get(str(r))
            if not (a and a["kind"] == "crash"):
                upto, cl = _cover_lines(changed, cov.get(str(r)) or {}, a)
                out.append(f"The lines you changed, as run {r} replays them ({upto}):\n" + "\n".join(cl))
        lines = out
    if getattr(C, "TICKET_PASSED", False):   # 6.11: факт о первом задетом удачном прогоне
        if watch is None:
            changed = changed or _changed_lines(run)
            watch = _watch(changed)
        pf = passed_fact(run, changed, watch or None, hide)
        if pf:
            lines.append(pf)
    run.w({"type": "ticket_check", "expected": exp, "runs": runs, "cur": cur, "code": code, "lines": lines,
           **({"cover": cov} if cover else {})})
    return "Check against the observation:\n" + "\n".join(lines)
