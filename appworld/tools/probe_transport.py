"""Same upstream request two ways on the live gateway: as upstream AppWorld sent it (openai client body:
None fields in assistant messages, cache_control on the last message, tools null) and as runner/llm.py
sends it. Also via 8089 (cap proxy). Compares reply text and prompt_tokens. 3 model calls."""
import json, sys, time
from pathlib import Path
import requests

calls = [json.loads(l) for l in open(Path.home() / "Projects/appworld/experiments/outputs/ornith9b_react_dev/tasks/0d8a4ee_1/logs/lm_calls.jsonl")]
c = calls[int(sys.argv[1]) if len(sys.argv) > 1 else 1]
up = {"model": "ornith15-9b", "messages": c["input"]["messages"], "tools": None, "seed": 100, "temperature": 0}
clean = {"model": "ornith15-9b", "messages": [{"role": m["role"], "content": m["content"]} for m in c["input"]["messages"]],
         "temperature": 0.0, "seed": 100}
out = {}
for name, url, body in (("upstream_body_8090", "http://127.0.0.1:8090/v1", up), ("ours_8090", "http://127.0.0.1:8090/v1", clean),
                        ("ours_8089", "http://127.0.0.1:8089/v1", clean)):
    t0 = time.time()
    r = requests.post(url + "/chat/completions", json=body, timeout=600).json()
    out[name] = {"content": r["choices"][0]["message"]["content"], "prompt_tokens": r["usage"]["prompt_tokens"],
                 "completion_tokens": r["usage"]["completion_tokens"], "sec": round(time.time() - t0, 1)}
logged = c["output"]["choices"][0]["message"]["content"]
print(json.dumps({k: {**v, "content": v["content"][:80], "same_as_ours_8090": v["content"] == out["ours_8090"]["content"],
                      "same_as_upstream_log_2026_10_17": v["content"] == logged} for k, v in out.items()}, indent=1))
