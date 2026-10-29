import json, sys, statistics as st, collections
run = sys.argv[1]
meta = sorted((json.loads(l) for l in open(f"{run}/meta.jsonl")), key=lambda m: m["run"])
nt = open(f"{run}/src/no_tool_call.md").read(); it = open(f"{run}/src/invalid_tool_call.md").read()
allsec = []
for m in meta:
    msgs = [json.loads(l) for l in open(f"{run}/logs/run_{m['run']}.jsonl")]
    asst = [x for x in msgs if x["role"] == "assistant"]
    no_tool = sum(1 for x in msgs if x["role"] == "user" and x["content"] == nt)
    bad = sum(1 for x in msgs if x["role"] == "user" and x["content"] == it)
    multi = sum(1 for x in asst if len(x.get("tool_calls") or []) > 1)
    nothing = sum(1 for x in msgs if x["role"] == "tool" and x["content"].startswith("Nothing happens."))
    # raw action not exactly in the offered list (parser had to match)
    offmatch = 0; prev = None
    for x in msgs:
        if x["role"] in ("user", "tool") and "AVAILABLE ACTIONS:" in (x["content"] or ""):
            prev = x["content"].split("AVAILABLE ACTIONS: ", 1)[1].rstrip("\n").split("\n")
        if x["role"] == "assistant" and x.get("tool_calls") and prev:
            try:
                a = list(json.loads(x["tool_calls"][0]["function"]["arguments"]).values())[0]
                offmatch += a.strip().lower() not in prev
            except Exception:
                pass
    secs = [c["sec"] for c in m["calls"]]; allsec += secs
    ttype = m["game"].split("/")[2].split("-")[0]
    print(f"run {m['run']} {ttype:32s} ok={m['ok']!s:5} {m['reason']:12s} calls={m['model_calls']:2d} env_steps={m['env_steps']:2d} "
          f"sec={m['sec']:6.1f} call_med={st.median(secs):4.1f} max_ctx={m['max_prompt_tokens']:5d} out_tok={m['completion_tokens']:5d} "
          f"no_tool={no_tool} bad_args={bad} multi_calls={multi} not_offered={offmatch} nothing_happens={nothing} append_only={m['append_only']}")
print("per-call sec: median %.1f p90 %.1f max %.1f n=%d" % (st.median(allsec), sorted(allsec)[int(.9*len(allsec))], max(allsec), len(allsec)))
fin = collections.Counter(c["finish_reason"] for m in meta for c in m["calls"]); print("finish reasons", dict(fin))
