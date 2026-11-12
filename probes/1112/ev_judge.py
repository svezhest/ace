"""EV3: оценщик правки на наборе — по одному вызову на правку, ответ в три строки (Where / What happens there / Verdict).

  python3 probes/1112/ev_judge.py ITEMS.json --stand think27 --out OUT.jsonl --work WORK [--only ID…] [--limit N]

Вход — probes/1112/ev_input.py (кэш в runs/ev_1112/inputs/). Профиль стенда — stands/<имя>.json (адрес шлюза,
рассуждение, температура, бюджет). Строка OUT: {state, label, cls, verdict, where_run, where_call, place_ok, sec,
content, reasoning, usage}. place_ok — названное место есть среди мест расхождения перепрогона (вызов K или K-1)."""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev_input as EI  # noqa: E402


def call(prof, system, user, seed):
    ag = prof["agent"]
    gw = prof["gateways"][ag["gateway"]]
    body = {"model": prof["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": ag["temperature"], "seed": seed, "max_tokens": ag["max_tokens"]}
    if ag["thinking"]:
        body["enable_thinking"] = True
        if ag.get("think_budget"):
            body["thinking_budget"] = ag["think_budget"]
    req = urllib.request.Request(f"http://127.0.0.1:{gw['port']}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.load(r)


def parse(text):
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    v = re.findall(r"Verdict:\s*\**\s*(Ok|OK|Failed|FAILED)", t)
    w = re.search(r"Where:\s*\**\s*run\s*(\d+)[^\n]*?call\s*(\d+)", t, flags=re.I)
    return (v[-1].capitalize() if v else None), (w.group(1) if w else None), (int(w.group(2)) if w else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items")
    ap.add_argument("--stand", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--states", default=os.path.join(ROOT, "runs/ev_1112/t1_states.jsonl"))
    ap.add_argument("--obs", default=os.path.join(ROOT, "runs/typed_1111/in/t1.txt"))
    ap.add_argument("--view", default=os.path.join(ROOT, "runs/full_1112/app_r1"))
    ap.add_argument("--bench", default="app")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    prof = json.load(open(os.path.join(ROOT, "stands", a.stand + ".json")))
    items = json.load(open(a.items))
    if a.only:
        items = [i for i in items if any(i["state"].startswith(o) for o in a.only)]
    if a.limit:
        items = items[: a.limit]
    rows = [json.loads(l) for l in open(a.states)]
    obs = re.sub(r"^Observation from a study of the agent's failed runs[^\n]*\n+", "", open(a.obs).read())
    cache = os.path.join(ROOT, "runs/ev_1112/inputs")
    os.makedirs(cache, exist_ok=True)
    done = {json.loads(l)["state"] for l in open(a.out)} if os.path.exists(a.out) else set()
    for it in items:
        if it["state"] in done:
            continue
        p = os.path.join(cache, it["state"] + ".txt")
        if not os.path.exists(p):
            row = next(r for r in rows if r["state"] == it["state"] and r["log"] == it["log"] and r["n"] == it["n"])
            open(p, "w").write(EI.build(row, rows, a.view, a.bench, obs, a.work))
        user = open(p).read()
        t0 = time.time()
        r = call(prof, EI.SYSTEM, user, a.seed)
        msg = r["choices"][0]["message"]
        content, reasoning = msg.get("content") or "", msg.get("reasoning_content") or msg.get("reasoning") or ""
        v, wr, wc = parse(content)
        div = next(x for x in rows if x["state"] == it["state"])["div"]
        d = div.get(wr) if wr else None
        place_ok = bool(d and d.get("call") and wc in (d["call"], d["call"] - 1))
        out = {"state": it["state"], "label": it["label"], "cls": it["cls"], "verdict": v, "where_run": wr,
               "where_call": wc, "place_ok": place_ok, "sec": round(time.time() - t0, 1), "chars_in": len(user),
               "content": content, "reasoning": reasoning, "usage": r.get("usage"), "stand": a.stand, "seed": a.seed}
        with open(a.out, "a") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        print(f"{time.strftime('%H:%M:%S')} {it['state'][:6]} {it['cls']:8} label={it['label']:6} verdict={v} "
              f"where=run {wr} call {wc} place_ok={place_ok} {out['sec']}s", flush=True)


if __name__ == "__main__":
    main()
