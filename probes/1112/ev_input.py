"""EV2: вход оценщика правки — промпт и сообщение по одному состоянию src из ev_states.py.

  python3 probes/1112/ev_input.py STATES.jsonl STATE_ID [--view runs/full_1112/app_r1 --bench app --obs IN.txt]

Сообщение: наблюдение; итоговый diff против исходного src; если правок в сессии было больше одной — ряд diff, каждая
против предыдущей версии; перепрогон всех прогонов полного вида (тот же отчёт, что видит писатель от tests/rerun.py,
ядро editor/rerun.py); по каждому прогону, который идёт иначе, — шаги перед местом расхождения (tests/runs.py steps).
Ответа проверки на промежуточные версии нет (автор: только на итоговое состояние); слов писателя нет."""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev_states as ES  # noqa: E402

SYSTEM = """You review an edit to the harness of an AI agent. The harness is the code and the prompts in src/ that run the agent (a language model) on tasks; the agent's runs on tasks are recorded in logs/. A colleague studied the failed runs and wrote an observation: what went wrong in a run and what in the harness should change. Another colleague then edited src/ to do that.

Your goal is to say whether the edit is right: whether, in the recorded runs, it changes what the harness does at the problem the observation describes, and leaves the harness as it was at the steps that were fine.

You get the observation; the edit as a diff against the original src/ (if the colleague edited several times, also each version as a diff against the one before it); and a replay of all recorded runs with the edited src/. The replay sends the model's recorded replies through the edited harness and stops each run at the first place where the harness does something different from the log; what the model would have done after that is not known. For each run that goes differently, you also get the steps of the log just before that place.

Answer in three lines:
Where: run N, model call K: the place in the replay that decides your verdict.
What happens there: one sentence: what the step in the log was, and what the edited harness does at it.
Verdict: Ok or Failed"""

_INTRO = SYSTEM.split("\n\nYour goal")[0]
_GIVEN = SYSTEM.split("\n\nYou get ")[1].split("\n\nAnswer in")[0]
_GOAL_V1 = "Your goal is to say whether the edit is right: whether, in the recorded runs, it changes what the harness does at the problem the observation describes, and leaves the harness as it was at the steps that were fine."
# EV6b (идея 2 сабагента 13.11): цель — двойное условие; «место, решающее вердикт» следует из него
_GOAL_AND = ("Your goal is to say whether the edit is right. It is right when, in the recorded runs, it changes what "
             "the harness does at the problem the observation describes, and every step where the edited harness acts "
             "differently from the log is part of that problem. A step that was fine in the log and is now handled "
             "differently makes the edit wrong.")
# EV6a (идея 1 сабагента и моя): по строке на каждый задетый прогон до вердикта — перебор, который рассуждение T
# делает молча, переносится в ответ NT
_FORM_RUNS = """Answer in this form. First, one line for each run that goes differently, in the order of the replay:
Run N, model call K: what the step in the log was, and whether it is part of the problem the observation describes or a step that was fine.
Then:
Where: run N, model call K: the place in the replay that decides your verdict.
Verdict: Ok or Failed"""
# описание входа по блокам (run_blocks): шаги лога до места и после него — после уже с прежним харнессом
_GIVEN_BLOCKS = _GIVEN.replace(
    "what the model would have done after that is not known. For each run that goes differently, you also get the "
    "steps of the log just before that place.",
    "what the model would have done after that with the edited harness is not known. For each run that goes "
    "differently, you also get the steps of the log just before that place and just after it (after it, the log "
    "shows what the model did with the original harness).")
assert _GIVEN_BLOCKS != _GIVEN
PROMPTS = {
    "v1": SYSTEM,
    "runs": f"{_INTRO}\n\n{_GOAL_V1}\n\nYou get {_GIVEN_BLOCKS}\n\n{_FORM_RUNS}",
    "runs_and": f"{_INTRO}\n\n{_GOAL_AND}\n\nYou get {_GIVEN_BLOCKS}\n\n{_FORM_RUNS}",
}
# EV10 (автор 13.11): во входе нет ряда версий правки — из описания входа убрана и его строка
_VERS = " (if the colleague edited several times, also each version as a diff against the one before it)"
assert _VERS in _GIVEN_BLOCKS
# EV12 (автор 13.11): шаги зовутся Step, без таблицы прогонов; форма ответа — «step K»
_FORM_RUNS_STEP = _FORM_RUNS.replace("Run N, model call K:", "Run N, step K:").replace("Where: run N, model call K:", "Where: run N, step K:")
assert _FORM_RUNS_STEP.count("step K") == 2
PROMPTS["runs_v2"] = f"{_INTRO}\n\n{_GOAL_V1}\n\nYou get {_GIVEN_BLOCKS.replace(_VERS, '')}\n\n{_FORM_RUNS_STEP}"
PROMPTS["runs_w"] = f"{_INTRO}\n\n{_GOAL_V1}\n\nYou get {_GIVEN_BLOCKS.replace(_VERS, '')}\n\n{_FORM_RUNS}"
# EV13 (автор 13.11): правку промпта смотрит отдельный оценщик — задача, промпт до и после; цель вместо запретов,
# без условия конкретной задачи
PROMPTS["prompt_edit"] = """You review an edit to the prompt of an AI agent (a language model) that works on tasks. A colleague studied the agent's failed runs and wrote an observation: what went wrong and what should change. Another colleague then edited the prompt to do that.

Your goal is to say whether the edited prompt is a good instruction for the agent on any task it may get:
- each new or changed instruction tells the agent what to do; where it says what not to do, it also says what to do instead;
- the prompt stays general: it carries no details of the particular task from the observation (its names, values or the exact condition of that task).

You get the observation, and each changed prompt file before and after the edit.

Answer in this form. First, one line for each new or changed passage of the prompt: what it tells the agent, and whether it meets both points.
Then:
Verdict: Ok or Failed"""
assert _GOAL_V1 in SYSTEM


def steps_text(work, run, call, before=6):
    a = max(1, call - before)
    b = max(a, call - 1)
    p = subprocess.run([sys.executable, "tests/runs.py", "steps", str(run), f"{a}-{b}"], cwd=work, capture_output=True,
                       text=True, timeout=60)
    lines = [l[:220] + ("…" if len(l) > 220 else "") for l in p.stdout.rstrip().splitlines()]
    return "\n".join(lines)


def _runs_mod(work):
    import importlib.util
    spec = importlib.util.spec_from_file_location("writer_runs", os.path.join(work, "tests", "runs.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _cap(lines, n, w):
    lines = [l.rstrip()[:w] + ("…" if len(l.rstrip()) > w else "") for l in lines]
    return lines[:n] + ([f"… (+{len(lines) - n} more lines)"] if len(lines) > n else [])


def steps_full(work, run, call, before=6):
    """Шаги K-before..K-1 с кодом целиком (runs.py steps показывает только первую строку кода — разные шаги выглядят
    одинаковыми, EV3 c6957a) и первыми строками ответа среды."""
    a, b = max(1, call - before), call - 1
    return (f"Run {run}: what the model sees at model call {call} differs from the log, so the edited harness acts "
            f"differently right after model call {call - 1} (the last step below). Steps {a}-{b} of the log:\n"
            + render_steps(work, run, a, b))


def _step_code(R, m):
    """Код шага: аргументы вызова инструмента или блоки ``` из текста ответа модели."""
    code = []
    for tc in m.get("tool_calls") or []:
        f = tc.get("function") or {}
        arg = f.get("arguments")
        try:
            arg = json.loads(arg) if isinstance(arg, str) else arg
        except ValueError:
            pass
        if isinstance(arg, dict) and len(arg) == 1 and isinstance(list(arg.values())[0], str):
            arg = list(arg.values())[0]
        code += (arg if isinstance(arg, str) else json.dumps(arg, ensure_ascii=False)).splitlines()
    if not code:
        t = R._text(m)
        blocks = re.findall(r"```[^\n]*\n(.*?)(?:```|$)", t, re.S)
        code = "\n".join(blocks).splitlines() if blocks else ["text: " + t.strip()]
    return [l for l in code if l.strip()]


def earlier_same(work, run, k):
    """EV8: на каких вызовах раньше в этом прогоне модель прислала тот же код, что на вызове k. Окно блока — 6 шагов;
    в run 9 (t1) прежние такие же шаги (9, 11, 12) вне окна, и шаг 19 выглядит первым — ложные «Failed» T и NT."""
    R = _runs_mod(work)
    objs = [R._obj(x) for x in open(os.path.join(work, "logs", f"run_{run}.jsonl"))]
    calls = [i for i, o in enumerate(objs) if R._is_model(o)]
    if not 1 <= k <= len(calls):
        return None, []
    codes = [_step_code(R, R._msg(objs[i])) for i in calls[:k]]
    kind = "action" if R._msg(objs[calls[k - 1]]).get("tool_calls") else "code"
    return kind, [j + 1 for j in range(k - 1) if codes[j] == codes[k - 1]]


def render_brief(work, run, a, b):
    """EV9: шаги a..b по строке — код шага в одну строку (строки через « ; ») и первая строка ответа. Окно в 6 шагов
    прячет начало прогона (run 9 t1: прогон начат заново после отказа прежнего харнесса на вызове 12); весь прогон
    до окна — без отбора, какие шаги показать (EV8: отбор «тот же код раньше» — наводка на цикл)."""
    R = _runs_mod(work)
    objs = [R._obj(x) for x in open(os.path.join(work, "logs", f"run_{run}.jsonl"))]
    calls = [i for i, o in enumerate(objs) if R._is_model(o)]
    a, b = max(1, a), min(b, len(calls))
    out = []
    for k in range(a, b + 1):
        i = calls[k - 1]
        code = " ; ".join(l.strip() for l in _step_code(R, R._msg(objs[i])))
        nxt = calls[k] if k < len(calls) else len(objs)
        env = next((objs[x] for x in range(i + 1, nxt) if objs[x] and objs[x].get("event") in ("env", "harness")
                    and isinstance(objs[x].get("message"), dict)), None)
        resp = [l.strip() for l in R._text(R._msg(env)).splitlines() if l.strip() and not l.strip().startswith("```")
                and l.strip() != "Output:" and re.search(r"\w", l)] if env else []
        who = "the harness did not run it and said" if env and env.get("event") == "harness" else "got"
        out.append(f"model call {k}: {_cap([code], 1, 160)[0]} → {who}: {_cap(resp[:1] or ['(nothing)'], 1, 100)[0]}")
    return "\n".join(out)


def render_steps(work, run, a, b, lab="model call"):
    R = _runs_mod(work)
    objs = [R._obj(x) for x in open(os.path.join(work, "logs", f"run_{run}.jsonl"))]
    calls = [i for i, o in enumerate(objs) if R._is_model(o)]
    a, b = max(1, a), min(b, len(calls))
    out = []
    for k in range(a, b + 1):
        i = calls[k - 1]
        m = R._msg(objs[i])
        code = _step_code(R, m)
        nxt = calls[k] if k < len(calls) else len(objs)
        # EV5b: первое сообщение модели после шага — от среды (env) или от харнесса (harness: прежняя защита не
        # исполнила код). В EV5 бралась только среда, и блок прежней защиты выглядел как «(no env message)».
        env = next((objs[x] for x in range(i + 1, nxt) if objs[x] and objs[x].get("event") in ("env", "harness")
                    and isinstance(objs[x].get("message"), dict)), None)
        resp = ([l for l in R._text(R._msg(env)).splitlines() if l.strip() and not l.strip().startswith("```")]
                if env else ["(no message)"])
        out.append(f"{lab} {k}, the model's {'action' if m.get('tool_calls') else 'code'}:")
        out += ["    " + l for l in _cap(code, 30, 200)]
        out.append("  the harness did not run it and said:" if env and env.get("event") == "harness" else "  the model got:")
        out += ["    " + l for l in _cap(resp, 4, 200)]
    return "\n".join(out)


EVENTS = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import rerun as R
new = R.worker(sys.argv[2], sys.argv[3], sys.argv[4])
res = R.results(sys.argv[4])
div = {}
for r, t in new.items():
    d = t["div"]
    if d is None:
        div[r] = None
        continue
    text = R.event_text(d, None) if R.event_of(d) else R.report_diff(new, None, res, [r], detail=True)
    div[r] = {"call": d.get("call"), "kind": d.get("kind"), "text": text}
print(json.dumps({"ok": {r: bool(res.get(r, {}).get("ok")) for r in new}, "div": div}))
"""


def run_blocks(bench, src, logs, work, before=6, after=3, earlier=False, brief=False, win=None, state="", sparse=None):
    """EV5: свой блок на каждый задетый прогон вместо отчёта rerun.py. Отчёт склеивает прогоны с похожим действием
    харнесса («The same as run 14») — у склеенного прогона нет ни своего кода, ни сообщения (ревью сабагента 13.11);
    вызов «model call K» в строке отчёта показывает код ответа K−1; деление на passed / failed читается как
    «безопасно». Здесь: предложение rerun.event_text по этому прогону (без склейки), шаги лога до места и после."""
    p = subprocess.run([sys.executable, "-c", EVENTS, os.path.join(ROOT, "editor"), bench, src, logs],
                       capture_output=True, text=True, timeout=900)
    j = json.loads(p.stdout.strip().splitlines()[-1])
    runs = sorted(j["div"], key=int)
    moved = [r for r in runs if j["div"][r]]
    same = [r for r in runs if not j["div"][r]]
    head = (f"{len(runs)} runs replayed with the edited src/. {len(moved)} go differently from the log: runs "
            f"{', '.join(moved) or 'none'}. The other {len(same)} go exactly as in the log. Each run is replayed up to "
            "the first place where the edited harness does something different from the log; from there on, what the "
            "model would do with the edited harness is not known. What the model did there with the original harness "
            "is in the log; for each run that goes differently, the steps of the log before and after that place are "
            "below.")
    out = [head]
    for r in moved:
        d = j["div"][r]
        k = d["call"]
        if win:
            # EV10 (автор 13.11): окно до места K−b−rand(n), rand(n) ∈ 0..n−1 — начала окон 6; 7..9; 10..14; 15..24 не пересекаются, у каждого прогона своё (зерно — правка и прогон);
            # заголовок без «in the log the task was solved / failed» (неясная строка; исход есть в таблице прогонов)
            import random
            before = win[0] + (random.Random(f"{state}:{r}").randrange(win[1]) if win[1] else 0)
            blk = [f"### Run {r}"]
        else:
            blk = [f"### Run {r} (in the log the task {'was solved' if j['ok'][r] else 'failed'})"]
        if d["kind"] == "model" and k and k > 1:
            blk.append(f"The edited harness acts differently right after model call {k - 1}. {d['text']}")
            if brief and k - before > 1:
                blk.append(f"The log from the start of the run, model calls 1-{k - before - 1}, one line per call "
                           "(the code on one line, and the first line of what came back):")
                blk.append(render_brief(work, r, 1, k - before - 1))
            if sparse:
                # EV11 (автор 13.11): к окну K−6…K+2 — по одному шагу из интервалов K−b−rand(n), b,n = 15,10; 10,5; 7,3
                # (начала K−24…K−15, K−14…K−10, K−9…K−7: растут и не пересекаются), каждый случайно, своё зерно
                import random
                picks = sorted({k - b - random.Random(f"{state}:{r}:{b}").randrange(n) for b, n in sparse})
                picks = [p for p in picks if 1 <= p < k - before]
                if picks:
                    blk.append(f"A few earlier steps of the log, picked at random, one at a time: model calls "
                               f"{', '.join(map(str, picks))}:")
                    blk.append("\n".join(render_steps(work, r, p, p) for p in picks))
            blk.append(f"The log before it, model calls {max(1, k - before)}-{k - 1} (the last one is the step the "
                       "edited harness handles differently):")
            blk.append(render_steps(work, r, k - before, k - 1))
            if earlier:
                kind, same_k = earlier_same(work, r, k - 1)
                blk.append(f"Earlier in this run, the model sent the same {kind} as at model call {k - 1} at model calls "
                           f"{', '.join(map(str, same_k))}." if same_k else
                           f"Earlier in this run, the model never sent the same {kind} as at model call {k - 1}.")
            aft = render_steps(work, r, k, k + after - 1)
            if aft:
                blk.append(f"The log after it, with the original harness, model calls {k}-{k + after - 1}:")
                blk.append(aft)
            else:
                blk.append("The log has no model calls after it.")
        else:
            blk.append(d["text"])
        out.append("\n".join(blk))
    return "\n\n".join(out)


def render_raw(work, run, a, b):
    """EV12 (автор 13.11: «правильнее вообще не толковать ответ и показывать его как есть»): шаг k — ответ модели как
    есть (текст и вызовы инструментов), затем каждое сообщение, пришедшее модели до следующего вызова, с источником из
    лога (env → Env, harness → Harness). Обрезка: ответ — 30 строк, сообщение — 6 строк, строка — 200 знаков."""
    R = _runs_mod(work)
    objs = [R._obj(x) for x in open(os.path.join(work, "logs", f"run_{run}.jsonl"))]
    calls = [i for i, o in enumerate(objs) if R._is_model(o)]
    a, b = max(1, a), min(b, len(calls))
    out = []
    for k in range(a, b + 1):
        i = calls[k - 1]
        m = R._msg(objs[i])
        lines = R._text(m).strip("\n").splitlines()
        for tc in m.get("tool_calls") or []:
            f = tc.get("function") or {}
            args = f.get("arguments")
            lines.append(f"tool call {f.get('name')}: " + (args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)))
        out.append(f"Step {k}")
        out.append("  Model:")
        out += ["    " + l for l in _cap(lines or ["(empty)"], 30, 200)]
        nxt = calls[k] if k < len(calls) else len(objs)
        got = [o for o in objs[i + 1:nxt] if o and isinstance(o.get("message"), dict)]
        for o in got:
            out.append(f"  {o.get('event', '?').capitalize()}:")
            out += ["    " + l for l in _cap(R._text(R._msg(o)).strip("\n").splitlines() or ["(empty)"], 6, 200)]
        if not got:
            out.append("  (the run ended here)" if k == len(calls) else "  (no message before the next step)")
    return "\n".join(out)


def _chars(work, run):
    """Знаков в сообщениях прогона: всего и до каждого вызова модели (список, индекс k−1 — до вызова k)."""
    R = _runs_mod(work)
    objs = [R._obj(x) for x in open(os.path.join(work, "logs", f"run_{run}.jsonl"))]
    tot, before = 0, []
    for o in objs:
        if not o or not isinstance(o.get("message"), dict):
            continue
        if R._is_model(o):
            before.append(tot)
        m = o["message"]
        tot += len(R._text(m)) + sum(len(json.dumps(tc, ensure_ascii=False)) for tc in m.get("tool_calls") or [])
    return tot, before


def run_blocks_v2(bench, src, logs, work, state, sparse=None, before=6, after=3):
    """EV12 (автор 13.11): без таблицы прогонов; заголовок прогона — исход, длина и место расхождения в знаках и шагах;
    «Context:» — шаги до места; «<-- Divergence point»; «Diff:» — что харнесс делал в логе и что делает теперь;
    шаги лога после места с оговоркой, что теперь они могут быть другими."""
    p = subprocess.run([sys.executable, "-c", EVENTS, os.path.join(ROOT, "editor"), bench, src, logs],
                       capture_output=True, text=True, timeout=900)
    j = json.loads(p.stdout.strip().splitlines()[-1])
    runs = sorted(j["div"], key=int)
    moved = [r for r in runs if j["div"][r]]
    out = [f"{len(runs)} runs replayed with the edited src/. {len(moved)} go differently from the log: runs "
           f"{', '.join(moved) or 'none'}. The other {len(runs) - len(moved)} go exactly as in the log. Each run is "
           "replayed up to the first place where the edited harness does something different from the log."]
    # EV13: прогоны, расходящиеся до шага 1 (правка промпта), — одним разделом, если текст расхождения у всех один
    # (без «run N (…):»); иначе — по блоку, как раньше. 20–30 одинаковых блоков нового не дают.
    lst = lambda d: (d["call"] - 1) if d["kind"] == "model" else (d["call"] or 0)
    first = [r for r in moved if lst(j["div"][r]) < 1]
    same = {re.sub(r"^run \d+ \([a-z]+\): ", "", j["div"][r]["text"]) for r in first}
    if len(first) > 1 and len(same) == 1:
        okr = [r for r in first if j["ok"][r]]
        bad = [r for r in first if not j["ok"][r]]
        out.append(f"### Runs {', '.join(first)}: they diverge before step 1, all in the same way.\n"
                   f"Previously OK (task solved): runs {', '.join(okr) or 'none'}. Previously NOT OK (task failed): "
                   f"runs {', '.join(bad) or 'none'}.\nDiff: {same.pop()}")
        moved = [r for r in moved if r not in first]
    for r in moved:
        d = j["div"][r]
        k = d["call"]
        tot, bef = _chars(work, r)
        prev = "OK (task solved)" if j["ok"][r] else "NOT OK (task failed)"
        # место — после шага last: для «what the model sees differs» call = K (расходится вход вызова K), для конца
        # эпизода, падения и задачи (end / crash / bridge) call = число сделанных вызовов
        last = (k - 1) if d["kind"] == "model" else (k or 0)
        k = last + 1
        if last < 1:
            out.append(f"### Run {r}: previously {prev}, {tot} chars, {len(bef)} steps; now diverges before step 1.\n"
                       f"Diff: {d['text']}")
            continue
        at = bef[k - 1] if k - 1 < len(bef) else tot
        blk = [f"### Run {r}: previously {prev}, {tot} chars, {len(bef)} steps; now diverges at {at} chars, after "
               f"step {k - 1}.", "Context:"]
        if sparse:
            import random
            picks = sorted({k - b - random.Random(f"{state}:{r}:{b}").randrange(n) for b, n in sparse})
            picks = [x for x in picks if 1 <= x < k - before]
            if picks:
                blk.append(f"(steps {', '.join(map(str, picks))} are picked at random from earlier in the run; then "
                           f"steps {max(1, k - before)}-{k - 1} in a row)")
                blk.append("\n".join(render_raw(work, r, x, x) for x in picks))
        blk.append(render_raw(work, r, k - before, k - 1))
        blk.append("<-- Divergence point")
        blk.append("Diff: " + d["text"])
        aft = render_raw(work, r, k, k + after - 1)
        if aft:
            blk.append("Note: the previous run continued with the following steps. They might not be the same now.")
            blk.append(aft)
        else:
            blk.append("Note: the previous run ended here.")
        out.append("\n".join(blk))
    return "\n\n".join(out)


def shuffle_report(report, rnd):
    """Задетые прогоны в отчёте перепрогона — в случайном порядке внутри своего раздела (строки «- run N, model call»)."""
    lines, out, i = report.split("\n"), [], 0
    while i < len(lines):
        if re.match(r"- run \d+, ", lines[i]):
            j = i
            while j < len(lines) and re.match(r"- run \d+, ", lines[j]):
                j += 1
            blk = lines[i:j]
            rnd.shuffle(blk)
            out += blk
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def is_prompt(rel):
    """Файл промпта харнесса (src/*.md) — его правку смотрит отдельный оценщик промпта (автор 13.11)."""
    return rel.endswith(".md")


def build_prompt(row, view, obs):
    """Оценщик промпта (автор 13.11): только задача (наблюдение), промпт до и промпт после. None — промпт не менялся."""
    src0 = ES.read_src(os.path.join(view, "src"))
    final = ES.chain(os.path.join(ROOT, row["log"]), src0)[: row["n"]][-1][1]
    changed = sorted(r for r in set(src0) | set(final) if is_prompt(r) and src0.get(r, "") != final.get(r, ""))
    if not changed:
        return None
    parts = [(obs.strip() if obs.lstrip().startswith("## ") else "## Observation\n" + obs.strip())]
    for rel in changed:
        parts.append(f"## {rel} before the edit\n```\n{src0.get(rel, '(no such file)').rstrip()}\n```")
        parts.append(f"## {rel} after the edit\n```\n{final.get(rel, '(file removed)').rstrip()}\n```")
    return "\n\n".join(parts)


def build(row, rows, view, bench, obs, work, full_steps=False, shuffle=None, blocks=False, earlier=False, brief=False, win=None, sparse=None, v2=False, logic_only=False):
    src0 = ES.read_src(os.path.join(view, "src"))
    sess = sorted((r for r in rows if r["log"] == row["log"] and r["n"] <= row["n"]), key=lambda r: r["n"])
    files = ES.chain(os.path.join(ROOT, row["log"]), src0)[: row["n"]]
    final = files[-1][1]
    if logic_only:
        # правки промпта вырезаются: файлы промпта — как в исходном src; если больше ничего не изменилось — пропуск
        final = {r: t for r, t in final.items() if not is_prompt(r)} | {r: t for r, t in src0.items() if is_prompt(r)}
        if final == src0:
            return None
    parts = [(obs.strip() if obs.lstrip().startswith("## ") else "## Observation\n" + obs.strip()),
             "## The edit (diff against the original src/)\n```diff\n" + ES.udiff(src0, final).rstrip() + "\n```"]
    if len(files) > 1 and not win and not v2:
        prev, ds = src0, []
        for k, (_, f) in enumerate(files, 1):
            ds.append(f"Version {k}:\n```diff\n" + ES.udiff(prev, f).rstrip() + "\n```")
            prev = f
        parts.append(f"## The versions of the edit, in the order they were made ({len(files)}; each diff is against the "
                     "version before it, the last one is the edit above)\n" + "\n\n".join(ds))
    with tempfile.TemporaryDirectory() as tmp:
        for rel, text in final.items():
            p = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(text)
        if v2:
            parts.append("## Replay of all recorded runs with the edited src/\n"
                         + run_blocks_v2(bench, os.path.join(tmp, "src"), os.path.join(view, "logs"), work, row["state"], sparse))
            return "\n\n".join(parts)
        if blocks:
            table = subprocess.run([sys.executable, "tests/runs.py"], cwd=work, capture_output=True, text=True).stdout.strip()
            parts.append("## The recorded runs\n" + table)
            parts.append("## Replay of all recorded runs with the edited src/\n"
                         + run_blocks(bench, os.path.join(tmp, "src"), os.path.join(view, "logs"), work, earlier=earlier, brief=brief, win=win, state=row["state"], sparse=sparse))
            return "\n\n".join(parts)
        rep = subprocess.run([sys.executable, ES.CORE, "--bench", bench, "--src", os.path.join(tmp, "src"),
                              "--logs", os.path.join(view, "logs")], capture_output=True, text=True, timeout=900)
    report = (rep.stdout or rep.stderr).strip().replace("on your src/", "on the edited src/")
    rnd = None
    if shuffle is not None:
        import random
        rnd = random.Random(f"{shuffle}:{row['state']}")
        report = shuffle_report(report, rnd)
    table = subprocess.run([sys.executable, "tests/runs.py"], cwd=work, capture_output=True, text=True).stdout.strip()
    parts.append("## The recorded runs\n" + table)
    parts.append("## Replay of all recorded runs with the edited src/\n" + report)
    sl = []
    div = sorted(row["div"].items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)
    if rnd:
        rnd.shuffle(div)
    for r, d in div:
        if d and r.isdigit() and d.get("call"):
            if full_steps:
                sl.append(steps_full(work, r, d["call"]))
            else:
                sl.append(f"Run {r}, before model call {d['call']}:\n" + steps_text(work, r, d["call"]))
    if sl:
        parts.append("## The steps of the log before each place where a run goes differently\n" + "\n\n".join(sl))
    return "\n\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("states")
    ap.add_argument("state")
    ap.add_argument("--view", default=os.path.join(ROOT, "runs/full_1112/app_r1"))
    ap.add_argument("--bench", default="app")
    ap.add_argument("--obs", default=os.path.join(ROOT, "runs/typed_1111/in/t1.txt"))
    ap.add_argument("--work", required=True, help="копия писателя с полными логами вида (для tests/runs.py)")
    ap.add_argument("--full-steps", action="store_true", help="шаги с кодом целиком (иначе runs.py steps)")
    ap.add_argument("--shuffle", help="зерно: задетые прогоны в отчёте и в шагах в случайном порядке")
    ap.add_argument("--blocks", action="store_true", help="EV5: блок на каждый задетый прогон (run_blocks)")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.states)]
    row = next(r for r in rows if r["state"].startswith(a.state))
    obs = open(a.obs).read()
    obs = re.sub(r"^Observation from a study of the agent's failed runs[^\n]*\n+", "", obs)
    print(build(row, rows, a.view, a.bench, obs, a.work, a.full_steps, a.shuffle, a.blocks))


if __name__ == "__main__":
    main()
