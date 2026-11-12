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


def build(row, rows, view, bench, obs, work):
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
    table = subprocess.run([sys.executable, "tests/runs.py"], cwd=work, capture_output=True, text=True).stdout.strip()
    parts.append("## The recorded runs\n" + table)
    parts.append("## Replay of all recorded runs with the edited src/\n" + report)
    sl = []
    for r, d in sorted(row["div"].items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        if d and r.isdigit() and d.get("call"):
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
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.states)]
    row = next(r for r in rows if r["state"].startswith(a.state))
    obs = open(a.obs).read()
    obs = re.sub(r"^Observation from a study of the agent's failed runs[^\n]*\n+", "", obs)
    print(build(row, rows, a.view, a.bench, obs, a.work))


if __name__ == "__main__":
    main()
