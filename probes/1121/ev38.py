"""EV38 (21.11): оценщик 9B по частям. Вход EV26/EV32 (`runs/evw_1113/ev25_in/v2/<тег>.txt`: наблюдение, правка,
блоки «### Run N») режется по прогонам:
  1) вызов на каждый прогон, который идёт иначе: наблюдение + правка + один блок -> одна строка «Run N, step K: …»;
  2) вызов-вывод: наблюдение + правка + строки шага 1 (своими словами модели) -> Where и Verdict;
  3) нет вердикта (или строки) — в той же беседе одна реплика: написать их сейчас.
Промпты — `runs_v2` с наименьшей правкой под часть входа. Правка без расходящихся прогонов — одним вызовом `runs_v2`.
  python3 probes/1121/ev38.py ПРОФИЛЬ SEED [потоков]   -> runs/evw_1113/ev38_<профиль>_s<seed>.jsonl"""
import json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "probes", "1112"))
import ev_input as EI  # noqa: E402
import ev_judge as EJ  # noqa: E402

H = os.path.join(ROOT, "runs", "evw_1113")
BASE = EI.PROMPTS["runs_v2"]
INTRO, GOAL = BASE.split("\n\n")[0], BASE.split("\n\n")[1]

PER_RUN = (INTRO + "\n\n" + GOAL + "\n\n"
    "You get the observation; the edit as a diff against the original src/; and the replay of one recorded run with "
    "the edited src/. The replay sends the model's recorded replies through the edited harness and stops the run at "
    "the first place where the harness does something different from the log; what the model would have done after "
    "that with the edited harness is not known. You also get the steps of the log just before that place and just "
    "after it (after it, the log shows what the model did with the original harness). Each run that goes "
    "differently is reviewed on its own in the same way; here you review this one run.\n\n"
    "Answer with one line:\n"
    "Run N, step K: what the step in the log was, what the edited harness does there instead, and whether the step "
    "is part of the problem the observation describes or a step that was fine.")

VERDICT = (INTRO + "\n\n" + GOAL + "\n\n"
    "You get the observation; the edit as a diff against the original src/; and a review of the replay of all "
    "recorded runs with the edited src/. The replay sends the model's recorded replies through the edited harness and "
    "stops each run at the first place where the harness does something different from the log. Each run that goes "
    "differently was reviewed on its own, from the steps of the log around that place; you get one line per run: "
    "what the step in the log was, what the edited harness does there instead, and whether the step is part of the "
    "problem the observation describes or a step that was fine.\n\n"
    "Answer in this form:\n"
    "Where: run N, step K: the place in the replay that decides your verdict.\n"
    "Verdict: Ok or Failed")

ASK_LINE = "Write the line now: Run N, step K: what the step was, what the edited harness does there instead, and whether it is part of the problem or a step that was fine."
ASK_VERDICT = "Write the Where and Verdict lines now."


def chat(prof, messages, seed):
    ag = prof["agent"]
    gw = prof["gateways"][ag["gateway"]]
    body = {"model": prof["model"], "messages": messages, "temperature": ag["temperature"], "seed": seed,
            "max_tokens": ag["max_tokens"], "prompt_cache": "read"}
    body.update(ag.get("sampling") or {})
    if ag["thinking"]:
        body["enable_thinking"] = True
        if ag.get("think_budget"):
            body["thinking_budget"] = ag["think_budget"]
    req = urllib.request.Request(f"http://127.0.0.1:{gw['port']}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        d = json.load(r)
    m = d["choices"][0]["message"]
    return m.get("content") or "", m.get("reasoning_content") or m.get("reasoning") or "", d.get("usage") or {}


def ask(prof, system, user, seed, done, follow):
    """Вызов + не больше одного добора в той же беседе -> (ответ, записи вызовов)."""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    calls = []
    for k in range(2):
        t0 = time.time()
        c, r, u = chat(prof, msgs, seed + 100 * k)
        calls.append({"content": c, "reasoning_chars": len(r), "usage": u, "sec": round(time.time() - t0, 1)})
        if done(c) or k:
            return c, calls
        msgs += [{"role": "assistant", "content": c}, {"role": "user", "content": follow}]


def line_of(c):
    m = re.search(r"(?im)^\W*Run\s+\d+,?\s+step\s+\d+.*$", re.sub(r"<think>.*?</think>", "", c, flags=re.S))
    return m.group(0).strip().strip("*-• ") if m else ""


def one(prof, seed, tag, label):
    s = open(os.path.join(H, "ev25_in", "v2", tag + ".txt")).read()
    i = s.find("### Run ")
    rec = {"tag": tag, "label": label, "runs": []}
    if i < 0:   # ни один прогон не идёт иначе — как раньше, одним вызовом
        c, calls = ask(prof, BASE, s, seed, lambda c: EJ.parse(c)[0], ASK_VERDICT)
        rec.update(mode="whole", content=c, calls=calls, verdict=EJ.parse(c)[0])
        return rec
    head, blocks = s[:i], re.split(r"\n(?=### Run )", s[i:])
    lines = []
    for b in blocks:
        c, calls = ask(prof, PER_RUN, head + b, seed, lambda c: bool(line_of(c)), ASK_LINE)
        n = re.match(r"### Run (\d+)", b).group(1)
        ln = line_of(c) or f"Run {n}: (no review line)"
        lines.append(ln)
        rec["runs"].append({"run": n, "line": ln, "content": c, "calls": calls})
    user = head.rstrip() + "\n\n## Review of each run that goes differently\n" + "\n".join(lines) + "\n"
    c, calls = ask(prof, VERDICT, user, seed, lambda c: EJ.parse(c)[0], ASK_VERDICT)
    rec.update(mode="split", content=c, calls=calls, verdict=EJ.parse(c)[0], chars_in=len(user))
    return rec


if __name__ == "__main__":
    stand, seed = sys.argv[1], int(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    prof = json.load(open(os.path.join(ROOT, "stands", stand + ".json")))
    out = os.path.join(H, f"ev38_{stand}_s{seed}.jsonl")
    done = {json.loads(l)["tag"] for l in open(out)} if os.path.exists(out) else set()
    items = [(r["tag"], r["label"]) for r in map(json.loads, open(os.path.join(H, "ev28_v2_eval9tc_s1.jsonl")))]
    todo = [x for x in items if x[0] not in done]
    with ThreadPoolExecutor(n) as ex:
        for r in ex.map(lambda x: one(prof, seed, *x), todo):
            open(out, "a").write(json.dumps(r, ensure_ascii=False) + "\n")
            print(time.strftime("%H:%M:%S"), r["tag"], r["label"], r["verdict"], len(r["runs"]), flush=True)
