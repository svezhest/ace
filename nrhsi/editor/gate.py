"""Проверки писателя: ответ на применённую правку (pyflakes, smoke, rerun, проверка по тикету) и ворота finish."""
import json
import os
import re
import subprocess

from .cfg import F
from . import cfg as C
from . import lint as LI
from . import work as WK

RERUN_CORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "editor", "rerun.py")   # ядро проверки по тикету


def smoke_failure(run):
    """Вывод python3 tests/smoke.py, если он упал ('' — прошёл)."""
    ok, out, full = WK.tool_run(run, "smoke")
    return "python3 tests/smoke.py now prints:\n" + out if not ok or "Traceback" in full else ""


def finish(run):
    """finish -> (текст для модели, конец ли). Ворота — новые предупреждения pyflakes и падение smoke — один раз:
    второй finish завершает как есть."""
    if run.st.get("lint_at_finish"):
        return "Finished.", True
    gate, smoke = LI.lint_changed(run.root), smoke_failure(run)
    if smoke:
        gate += ("\n" if gate else "") + smoke
    run.st["lint_at_finish"] = True
    if not gate:
        return "Finished.", True
    return f"Not finished yet. {gate}\nFix them with edit, or call finish again to end as is.", False


def clip(t, n):
    return t if len(t) <= n else t[:n] + f"\n[... {len(t)} characters in all]"


def smoke_scenarios(full):
    """Вывод smoke -> [(заголовок сценария, строка исхода, [с чего разговор начинается и что харнесс в него добавил])].
    Начало — строка «before reply 1: N messages (роли)»: число и роли стартовых сообщений, без их текста."""
    out = []
    for block in full.split("\n== ")[1:]:
        lines = block.splitlines()
        out.append((lines[0], lines[1].strip() if len(lines) > 1 else "",
                    [x.strip() for x in lines[2:] if x.startswith(("  after ", "  before reply 1:")) and "nothing besides" not in x]))
    return out


def smoke_line(added, start0):
    """Строка сценария: начало разговора называется, только если оно не такое, как до правок."""
    said = [x for x in added if not x.startswith("before reply 1:")]
    start = [x for x in added if x.startswith("before reply 1:") and x not in start0]
    return "; ".join(start + said) if start + said else "nothing besides the environment results"


def smoke_added(run, full):
    """10.11: что харнесс добавляет в разговор на заглушке — фактом в ответе на правку, а не «runs without errors».
    Сравнение с тем же smoke на src до правок (tests/orig_src)."""
    now = smoke_scenarios(full)
    if not now:
        return ""
    if run.smoke0 is None:
        run.smoke0 = smoke_scenarios(WK.tool_run(run, "smoke", " tests/orig_src")[2])
    if now == run.smoke0:
        return " With the stub task and model the harness says the same as before your edits."
    t = " With the stub task and model, where no reply and no answer is ever repeated, the harness now says:"
    was = dict((h, a) for h, _, a in run.smoke0)
    for head, end, added in now:
        t += f"\n  {head}: " + smoke_line(added, was.get(head, []))
        if run.smoke0 and end != dict((h, e) for h, e, _ in run.smoke0).get(head):
            t += f" ({end})"
    if run.smoke0:
        t += "\n  before your edits:"
        new = dict((h, a) for h, _, a in now)
        for head, end, added in run.smoke0:
            t += f"\n  {head}: " + smoke_line(added, new.get(head, []))
    return t


def edit_checks(run):
    """Ответ на применённую правку (4.11): новые предупреждения pyflakes, smoke, rerun всех прогонов и проверка по тикету.
    bash на это не тратится."""
    lint_ = LI.lint_changed(run.root)
    ok, out, full = WK.tool_run(run, "smoke")
    smoke = ("python3 tests/smoke.py prints:\n" + out if not ok or "Traceback" in full else
             "python3 tests/smoke.py runs without errors." + smoke_added(run, full))
    rerun = clip(WK.tool_run(run, "rerun")[2].strip(), F.OUT_CHARS)
    t = ("Checks run on src/ after this edit (they use no bash calls):\n" + (lint_ + "\n" if lint_ else "") + smoke
         + "\npython3 tests/rerun.py prints:\n" + clip(rerun, C.RERUN_CHARS).rstrip())
    return t + ("\n\n" + ticket_check(run) if C.TICKET else "")


# ---------------------------------------------------------------- 6.11: проверка по тикету
# Ожидание ревьювера change_expected: prompt | control | any — в тикете; писатель видит его абзацем в наблюдении.
# prompt — меняется то, что модель читает (тексты .md в src/); control — меняется то, что делает код харнесса
# (видно, если вернуть тексты .md как в виде); any — что-то из двух. После каждой авто-проверки — Ok / Failed: причина.

def _replay(src, root, runs, cover=False, watch=None):
    cmd = ([os.path.join(F.BIN, "python3"), RERUN_CORE, "--bench", C.BENCH, "--src", src, "--logs", f"{root}/logs", "--json"]
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
    out, syn = [], []
    safe = _safe

    def gen(n):
        return (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("all", "any")
                and n.args and isinstance(n.args[0], (ast.GeneratorExp, ast.ListComp)))

    def walk(n, acc, neg=False, top=True):
        if isinstance(n, ast.BoolOp):
            for v in n.values:
                walk(v, acc, neg, top)
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            walk(n.operand, acc, not neg, top)
        elif isinstance(n, ast.Compare):
            for v in [n.left] + n.comparators:
                walk(v, acc, neg, False)
        elif gen(n) and top:
            # all/any(E for x in X): значение целиком — то же «never true». Показываем X и элемент, который решил исход:
            # первый, где E ложно (all) или истинно (not any); если исход решили все элементы — последний.
            comp = n.args[0]
            walk(comp.generators[0].iter, acc, top=False)
            if not safe(n):
                return
            elt, clauses = ast.unparse(comp.elt), "".join(ast.unparse(g) for g in comp.generators)
            tgt = [ast.unparse(g.target) for g in comp.generators]
            tgt = tgt[0] if len(tgt) == 1 else "(" + ", ".join(tgt) + ")"
            inner = []
            walk(comp.elt, inner, top=False)
            first = (n.func.id == "all") != neg
            if first:
                want = f"not ({elt})" if n.func.id == "all" else f"({elt})"
                wrap = lambda x: f"next(({x}{clauses} if {want}))"
                head = f"{'false' if n.func.id == 'all' else 'true'} first at "
            else:
                wrap = lambda x: f"[{x}{clauses}][-1]"
                head = "at the last item "
            bound = {x.id for g in comp.generators for x in ast.walk(g.target) if isinstance(x, ast.Name)}
            for i, x in enumerate([tgt] + [x for x in dict.fromkeys(inner) if x not in bound][:3]):   # имена цели уже показаны
                _SYN[wrap(x)] = (head if i == 0 else "", x)
                syn.append(wrap(x))
        elif not isinstance(n, ast.Constant) and safe(n):
            acc.append(ast.unparse(n))
    walk(tree, out)
    return list(dict.fromkeys(out))[:4] + list(dict.fromkeys(syn))


_SYN = {}   # выражение-проба для элемента all/any -> (вводные слова, что показать писателю)


def _is_err(v):
    """Ошибка вычисления операнда — обычно короткое замыкание (`out and out.get(...)` при out = None) или элемента нет
    (StopIteration у пробы all/any): такой операнд условие не вычисляло, показывать его нельзя. Сюда же значение без
    содержания — `<zip object at 0x…>`."""
    return isinstance(v, str) and v.startswith("<") and v.endswith(">") and (
        any(t in v for t in ("Error", "Exception", "StopIteration")) or re.fullmatch(r"<[^<>]* at 0x[0-9a-f]+>", v) is not None)


def _show_vals(vals):
    """«`a` = 1, false first at `b` = 0: `x[b]` = (), `y` = 2»: после элемента all/any — двоеточие и его операнды."""
    s, head = "", False
    for e, v in vals.items():
        pre, name = _SYN.get(e, ("", e))
        s += ((": " if head else ", ") if s else "") + f"{pre}`{name}` = {v}"
        head = bool(pre)
    return s


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


def _dead_fact(changed, cov):
    """Одна фраза для строки Failed (6.11): до двух изменённых условий, которые выполнялись и ни разу
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
        def with_vals(c):   # значения операндов условия на его последнем выполнении
            val = (cov.get("__val__") or {}).get(c[2])
            vals = {e: v for e, v in ((val or {}).get("vals") or {}).items() if not _is_err(v)}
            if not vals:
                return c[1]
            return c[1] + f" (at its last run, before model call {val['call'] + 1}: " + _show_vals(vals) + ")"
        return "your " + "; your ".join(with_vals(c) for c in cand[:2])
    if dead:
        return f"your `{dead[2][:80]}` at src/{dead[1]}:{dead[0]} never ran"
    return None if any_ran else "none of the lines you changed ran in it"


def _shadowed(changed):
    """Изменённые строки внутри def, который ниже в том же модуле или классе перекрыт def с тем же именем
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


def _why_fact(changed, cov, r):
    """Почему изменённые строки не выполнялись: их def перекрыт ниже определением с тем же именем. Факт прогона."""
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
    return res[:2]


def _old_texts_src(run):
    """Копия src/ писателя, где все .md — как в виде (новые .md убраны): остаётся только код."""
    import shutil
    view = f"{C.VIEWS[C.BENCH]}/src"
    t = f"{C.HERE}/.ticket_{os.path.basename(run.root)}"   # 6.11: не в work/ — «..» копии писателя не меняет время
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


def _passed_runs(root):
    """Номера прогонов вида, которые в логе удались (logs/results.jsonl)."""
    out = []
    for l in open(f"{root}/logs/results.jsonl"):
        r = json.loads(l)
        if r.get("ok"):
            out.append(str(r["run"]))
    return out


def _passed_rest(run, texts, named):
    """12.11: удачные прогоны, не названные тикетом, по умолчанию должны идти как в логе. Сравнивать можно только прогоны,
    записанные на этом харнессе: прогон, который расходится уже на исходном src/ вида, в проверку не входит. Смена одного
    текста сообщения харнесса (поведение то же) — не нарушение. При правке текстов .md — код с текстами из вида."""
    rest = [r for r in _passed_runs(run.root) if r not in named]
    if not rest:
        return []
    if not hasattr(run, "_base_div"):
        run._base_div = _replay(f"{C.VIEWS[C.BENCH]}/src", run.root, rest)
    rest = [r for r in rest if run._base_div.get(r) is None]
    div = _replay(_old_texts_src(run) if texts else f"{run.root}/src", run.root, rest)
    old = " (with the old texts)" if texts else ""
    same = [r for r in rest if div.get(r) is None]
    worded = [r for r in rest if div.get(r) and (div[r].get("event") or "").startswith("reworded")]
    hit = [r for r in rest if div.get(r) and r not in worded]
    lines = []
    for r in hit[:3]:
        d = div[r]
        if d["kind"] == "crash":
            lines.append(f"Failed: in run {r}, which passed, the harness now crashes" + (f" at model call {d['call']}" if d["call"] else "")
                         + f": {d['text'].strip().splitlines()[0][:300] if d['text'].strip() else 'no message'}")
        else:
            lines.append(f"Failed: this edit changes run {r}, which passed and should still go exactly as in the log; "
                         + ("with the old texts " if texts else "") + f"{_where(d)}.")
    if len(hit) > 3:
        more = hit[3:]
        lines.append(f"Failed: this edit also changes run{'s' if len(more) > 1 else ''} {', '.join(more)}, which passed and "
                     "should still go exactly as in the log.")
    if worded:
        lines.append(f"Ok: in run{'s' if len(worded) > 1 else ''} {', '.join(worded)}, which passed, the harness does the same "
                     f"as in the log{old}; only the text of its message is different.")
    if same:
        n = len(same)
        lines.append((f"Ok: the other {n} runs that passed" if n > 1 else f"Ok: run {same[0]}, which passed,")
                     + f" still go{'es' if n == 1 else ''} exactly as in the log{old}.")
    return lines


def ticket_check(run):
    """Проверка по тикету после правки: по строке Ok / Failed на прогон тикета (и на прогон keep). К Failed «как в логе» —
    факт проигрыша: какое изменённое условие выполнялось и ни разу не было истинным, со значениями операндов на последнем
    выполнении, или что изменённые строки не выполнялись (и почему, если их def перекрыт)."""
    exp, runs = C.TICKET["change_expected"], C.TICKET["runs"]
    changed = _changed_lines(run)
    watch = _watch(changed)
    watch["__shape__"] = True   # длинные строки — началом, концом и размером
    cur, cov = _replay(f"{run.root}/src", run.root, runs, cover=True, watch=watch)
    texts = _texts_differ(run)
    code, cov_code = _replay(_old_texts_src(run), run.root, runs, cover=True, watch=watch) if texts else (cur, cov)
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
                lines.append(f"Failed: this edit has no effect in run {r}, the run the observation is about.")
        elif exp == "prompt":
            if prompt_eff:
                lines.append(f"Ok: in run {r} the texts the model reads have changed: {_where(a)}.")
            elif code_eff:
                lines.append(f"Failed: in run {r} the texts the model reads are as before; only the harness code acts "
                             f"differently: {_where(b)}.")
            else:
                lines.append(f"Failed: this edit has no effect in run {r}, the run the observation is about.")
        else:
            if prompt_eff or code_eff:
                lines.append(f"Ok: run {r} changes: {_where(a or b)}.")
            else:
                lines.append(f"Failed: this edit has no effect in run {r}, the run the observation is about.")
    if changed:   # факт покрытия — в саму строку Failed «как в логе»
        for i, r in enumerate(runs):
            if lines[i].startswith(f"Failed: this edit has no effect in run {r}"):
                c = cov.get(str(r)) or {}
            elif lines[i].startswith(f"Failed: in run {r} only the texts the model reads have changed"):
                c = cov_code.get(str(r)) or {}   # код без новых текстов идёт как в логе — факт о нём
            else:
                continue
            f = [x for x in [_dead_fact(changed, c)] if x] + _why_fact(changed, c, r)
            if f:
                lines[i] = lines[i].rstrip(".") + f"; in run {r} " + "; ".join(f) + "."
    keep = C.TICKET.get("keep") or []   # вторая половина тикета (6.11 TKK): прогоны, которые должны пойти как в логе
    if keep:
        kc = _replay(f"{run.root}/src", run.root, keep)
        kk = _replay(_old_texts_src(run), run.root, keep) if texts else kc
        for r in keep:
            a, b = kc.get(str(r)), kk.get(str(r))
            crash = next((d for d in (a, b) if d and d["kind"] == "crash"), None)
            d = b if texts else a   # при правке текстов все прогоны меняются со старта: «остаться» проверяется по коду
            if crash:
                lines.append(f"Failed: in run {r} the harness crashes" + (f" at model call {crash['call']}" if crash["call"] else "")
                             + f": {crash['text'].strip().splitlines()[0][:300] if crash['text'].strip() else 'no message'}")
            elif d is None:
                lines.append(f"Ok: run {r}, which passed, still goes exactly as in the log"
                             + (" (with the old texts)" if texts else "") + ".")
            else:
                lines.append(f"Failed: this edit changes run {r}, which passed and should still go exactly as in the log; "
                             + ("with the old texts " if texts else "") + f"{_where(d)}.")
    lines += _passed_rest(run, texts, {str(r) for r in list(runs) + list(keep)})
    run.w({"type": "ticket_check", "expected": exp, "runs": runs, "cur": cur, "code": code, "lines": lines})
    return "Check against the observation:\n" + "\n".join(lines)
