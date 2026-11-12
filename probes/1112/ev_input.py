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
    R = _runs_mod(work)
    objs = [R._obj(x) for x in open(os.path.join(work, "logs", f"run_{run}.jsonl"))]
    calls = [i for i, o in enumerate(objs) if R._is_model(o)]
    a, b = max(1, call - before), min(call - 1, len(calls))
    out = [f"Run {run}: what the model sees at model call {call} differs from the log, so the edited harness acts "
           f"differently right after model call {call - 1} (the last step below). Steps {a}-{b} of the log:"]
    for k in range(a, b + 1):
        i = calls[k - 1]
        m = R._msg(objs[i])
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
        code = [l for l in code if l.strip()]
        nxt = calls[k] if k < len(calls) else len(objs)
        env = next((objs[x] for x in range(i + 1, nxt) if R._is_env(objs[x])), None)
        resp = ([l for l in R._text(R._msg(env)).splitlines() if l.strip() and not l.strip().startswith("```")]
                if env else ["(no env message)"])
        out.append(f"model call {k}, the model's code:")
        out += ["    " + l for l in _cap(code, 30, 200)]
        out.append("  the model got:")
        out += ["    " + l for l in _cap(resp, 4, 200)]
    return "\n".join(out)


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


def build(row, rows, view, bench, obs, work, full_steps=False, shuffle=None):
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
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.states)]
    row = next(r for r in rows if r["state"].startswith(a.state))
    obs = open(a.obs).read()
    obs = re.sub(r"^Observation from a study of the agent's failed runs[^\n]*\n+", "", obs)
    print(build(row, rows, a.view, a.bench, obs, a.work, a.full_steps, a.shuffle))


if __name__ == "__main__":
    main()
