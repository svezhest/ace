"""Ручной режим (6.11): точечный вопрос модели без агентской обвязки — наблюдение (+код по его ссылкам) и вопрос.
Батарея — JSON-список {id, obs, form (v|s), code (bool), turns: [вопрос, {"assistant": подставленный ответ}, вопрос-продолжение, ...]}; по N сэмплов.
python3 -m nrhsi.editor.ask BATTERY.json OUT.jsonl --samples 5"""
import argparse
import glob
import json
import os
import re

from . import inputs as IN
from ..researcher import cfg as RC
from ..researcher import model as M
from ..researcher import policy as POL

R = "/Users/user/Projects/nrhsi"


def view_src(obs):
    p = glob.glob(f"{R}/runs/manual_1103/v2/obs/{obs}_*.md")[0]
    return R + "/" + re.match(r"<!-- вид: (\S+)", open(p).read()).group(1) + "/src"


def first(q):
    t = open(f"{R}/runs/manual_1103/v2/in/{q['obs']}_{q.get('form', 'v')}_rr.txt").read().rstrip()
    if q.get("code"):
        t += IN.given_code(t, view_src(q["obs"]))
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("battery")
    ap.add_argument("out")
    ap.add_argument("--samples", type=int, default=5)
    a = ap.parse_args()
    POL.apply_stand("default")
    done = set()
    if os.path.exists(a.out):
        done = {(r["id"], r["k"]) for r in map(json.loads, open(a.out))}
    for q in json.load(open(a.battery)):
        ctx = first(q)
        for k in range(1, a.samples + 1):
            if (q["id"], k) in done:
                continue
            seed = 61100 + k * 1000 + sum(map(ord, q["id"])) % 997
            msgs, answers = [], []
            for i, turn in enumerate(q["turns"]):
                if isinstance(turn, dict):   # подставленный ответ модели (атрибуция «твоя правка»)
                    msgs.append({"role": "assistant", "content": turn["assistant"]})
                    answers.append(None)
                    continue
                msgs.append({"role": "user", "content": (ctx + "\n\n" + turn) if i == 0 else turn})
                if i + 1 < len(q["turns"]) and isinstance(q["turns"][i + 1], dict):
                    continue
                resp, err = M.chat(msgs, RC.TEMP, seed)
                txt = err or ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                answers.append(txt)
                msgs.append({"role": "assistant", "content": txt})
            with open(a.out, "a") as f:
                f.write(json.dumps({"id": q["id"], "obs": q["obs"], "k": k, "seed": seed, "turns": q["turns"],
                                    "answers": answers}, ensure_ascii=False) + "\n")
            print(q["id"], k, len(answers[-1]), flush=True)


if __name__ == "__main__":
    main()
