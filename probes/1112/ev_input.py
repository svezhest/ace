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


def render_steps(work, run, a, b):
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
        out.append(f"model call {k}, the model's {'action' if m.get('tool_calls') else 'code'}:")
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


def run_blocks(bench, src, logs, work, before=6, after=3, earlier=False, brief=False):
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
        blk = [f"### Run {r} (in the log the task {'was solved' if j['ok'][r] else 'failed'})"]
        if d["kind"] == "model" and k and k > 1:
            blk.append(f"The edited harness acts differently right after model call {k - 1}. {d['text']}")
            if brief and k - before > 1:
                blk.append(f"The log from the start of the run, model calls 1-{k - before - 1}, one line per call "
                           "(the code on one line, and the first line of what came back):")
                blk.append(render_brief(work, r, 1, k - before - 1))
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


def build(row, rows, view, bench, obs, work, full_steps=False, shuffle=None, blocks=False, earlier=False, brief=False):
    src0 = ES.read_src(os.path.join(view, "src"))
    sess = sorted((r for r in rows if r["log"] == row["log"] and r["n"] <= row["n"]), key=lambda r: r["n"])
    files = ES.chain(os.path.join(ROOT, row["log"]), src0)[: row["n"]]
    final = files[-1][1]
    parts = [(obs.strip() if obs.lstrip().startswith("## ") else "## Observation\n" + obs.strip()),
             "## The edit (diff against the original src/)\n```diff\n" + ES.udiff(src0, final).rstrip() + "\n```"]
    if len(files) > 1:
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
        if blocks:
            table = subprocess.run([sys.executable, "tests/runs.py"], cwd=work, capture_output=True, text=True).stdout.strip()
            parts.append("## The recorded runs\n" + table)
            parts.append("## Replay of all recorded runs with the edited src/\n"
                         + run_blocks(bench, os.path.join(tmp, "src"), os.path.join(view, "logs"), work, earlier=earlier, brief=brief))
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
