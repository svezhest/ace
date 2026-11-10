"""Воспроизводит ли editor/fork.py записанный ход: тот же запрос, тот же seed — ответ должен совпасть дословно.
python3 probes/1110/forkcheck_repro.py LOG STAND T1 T2 ...   (по одному запросу к модели на ход)
"""
import json
import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
log, stand, turns = sys.argv[1], sys.argv[2], [int(t) for t in sys.argv[3:]]
recs = [json.loads(line) for line in open(log)]
seed0 = recs[0]["seed"]
by = {r["i"]: r for r in recs if r.get("type") == "turn"}
for t in turns:
    out = f"{log}.repro{t}.jsonl"
    cmd = [sys.executable, f"{ROOT}/editor/fork.py", log, "--turn", str(t), "--n", "1", "--seed0", str(seed0 + t - 1),
           "--stand", stand, "--out", out] + (["--final"] if by[t]["final"] else [])
    subprocess.run(cmd, check=True, capture_output=True)
    o, r = json.loads(open(out).readline()), by[t]
    same = {"content": (o.get("content") or "") == (r.get("content") or ""),
            "reasoning": (o.get("reasoning") or "") == (r.get("reasoning") or ""),
            "calls": [(c["name"], c["arguments"]) for c in o["calls"]] == [(c["name"], c["arguments"]) for c in r["tool_calls"]],
            "gen": o["usage"].get("completion_tokens") == r["usage"].get("completion_tokens"),
            "prompt": o["usage"].get("prompt_tokens") == r["usage"].get("prompt_tokens")}
    print(json.dumps({"turn": t, "final": r["final"], "calls": [c["name"] for c in r["tool_calls"]], **same,
                      "prompt_tokens": [r["usage"].get("prompt_tokens"), o["usage"].get("prompt_tokens")]}), flush=True)
