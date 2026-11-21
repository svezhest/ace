"""EV42 (21.11): оценщик 9B на целом входе EV26 (runs_v2) + две ступени EV39/EV41: как устроен шаг во входе и
«сначала правило из наблюдения». Остальное — как EV32/EV34 (вход, форма ответа, разбор вердикта).
  python3 probes/1121/ev42.py ПРОФИЛЬ SEED [потоков] -> runs/evw_1113/ev42_<профиль>_s<seed>.jsonl"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev38  # noqa: E402

P = ev38.BASE.split("\n\n")
# третий абзац — описание входа: после фразы о шагах до и после места — как устроен шаг (EV39)
P[2] = P[2] + ev38.LAYOUT
# форма ответа: сначала правило из наблюдения (EV41), затем строки по прогонам, Where и Verdict — как было
P[3] = ("First write, in one sentence, what the observation says makes a step part of the problem. Then check each "
        "run against it, using what the input shows. Then a" + P[3][1:])
SYSTEM = "\n\n".join(P)


def one(prof, seed, tag, label):
    s = open(os.path.join(ev38.H, "ev25_in", "v2", tag + ".txt")).read()
    c, calls = ev38.ask(prof, SYSTEM, s, seed, lambda c: ev38.EJ.parse(c)[0], ev38.ASK_VERDICT)
    return {"tag": tag, "label": label, "verdict": ev38.EJ.parse(c)[0], "content": c, "calls": calls, "chars_in": len(s)}


if __name__ == "__main__":
    stand, seed = sys.argv[1], int(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    prof = json.load(open(os.path.join(ev38.ROOT, "stands", stand + ".json")))
    out = os.path.join(ev38.H, f"ev42_{stand}_s{seed}.jsonl")
    done = {json.loads(l)["tag"] for l in open(out)} if os.path.exists(out) else set()
    items = [(r["tag"], r["label"]) for r in map(json.loads, open(os.path.join(ev38.H, "ev28_v2_eval9tc_s1.jsonl")))]
    with ThreadPoolExecutor(n) as ex:
        for r in ex.map(lambda x: one(prof, seed, *x), [x for x in items if x[0] not in done]):
            open(out, "a").write(json.dumps(r, ensure_ascii=False) + "\n")
            print(time.strftime("%H:%M:%S"), r["tag"], r["label"], r["verdict"], flush=True)
