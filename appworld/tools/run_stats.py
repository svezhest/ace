"""Summary of runs/<tag>/meta.jsonl: per episode and model time. .venv/bin/python -I tools/run_stats.py smoke1 material1"""
import json, statistics as st, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
allm, allc = [], []
for tag in sys.argv[1:]:
    for l in open(ROOT / "runs" / tag / "meta.jsonl"):
        m = json.loads(l)
        allm.append(m)
        allc += m["calls"]
        ev = m["evaluation"]
        print(f"{tag:10} run {m['run']:2} {m['task']:10} {m['reason']:<14} calls={m['model_calls']:2} sec={m['sec']:6} "
              f"ctx={m['max_prompt_tokens']:6} out={m['completion_tokens']:5} checks={ev['num_tests'] - len(ev['failures'])}/{ev['num_tests']}")
secs = sorted(m["sec"] for m in allm)
lat = sorted(c["sec"] for c in allc)
model_sec = sum(lat)
reasons = {}
for m in allm:
    reasons[m["reason"]] = reasons.get(m["reason"], 0) + 1
print(json.dumps({"episodes": len(allm), "ok": sum(m["ok"] for m in allm), "reasons": reasons,
                  "episode_sec_median": st.median(secs), "episode_sec_mean": round(st.mean(secs), 1),
                  "episode_sec_max": secs[-1], "calls": len(lat), "call_sec_median": st.median(lat),
                  "call_sec_p90": lat[int(0.9 * (len(lat) - 1))], "call_sec_max": lat[-1],
                  "model_sec_total": round(model_sec), "max_prompt_tokens": max(m["max_prompt_tokens"] for m in allm),
                  "max_completion_tokens_one_call": max((c["completion_tokens"] or 0) for c in allc),
                  "finish_length": sum(c["finish_reason"] == "length" for c in allc)}, indent=1))
