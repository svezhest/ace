"""R1 (20.11): развилка на один ход писателя. Беседа восстанавливается по логу сессии (meta: system, first_user,
tool_schemas; turn: content, reasoning, tool_calls, results.shown; note — реплика пользователя) до хода N, затем
N-й ход берётся заново с разными seed. Проверка восстановления: seed исходного хода (seed сессии + N - 1) должен
повторить записанный ход (выборка с seed при QWEN_BATCH_INVARIANT=1; при 3+ строках в батче почти равные
вероятности могут перевернуть токен — тогда совпадение не гарантировано).
  cd ~/Projects/nrhsi-wc && python3 ~/Projects/nrhsi/probes/1120/fork_next.py ЛОГ N ПРОФИЛЬ K   → ЛОГ_forkN.jsonl"""
import json
import sys

sys.path.insert(0, ".")
from nrhsi.researcher import cfg as C, model as F, policy  # noqa: E402

log, N, stand, K = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
rows = [json.loads(l) for l in open(log)]
meta = rows[0]
policy.apply_stand(stand)
assert bool(meta.get("think_history")) == C.THINK_HISTORY, "профиль не совпадает с сессией по think_history"
msgs = [{"role": "system", "content": meta["system"]}, {"role": "user", "content": meta["first_user"]}]
orig = None
for r in rows[1:]:
    if r.get("type") == "turn":
        if r["i"] == N:
            orig = r
            break
        a = {"role": "assistant", "content": r.get("content") or ""}
        if C.THINK_HISTORY and r.get("reasoning"):
            a["reasoning_content"] = r["reasoning"]
        ids = [f"call_{r['i'] - 1}_{j}" for j in range(len(r.get("tool_calls") or []))]
        if r.get("tool_calls"):
            a["tool_calls"] = [{"id": ids[j], "type": "function", "function": c} for j, c in enumerate(r["tool_calls"])]
        msgs.append(a)
        for j, res in enumerate(r.get("results") or []):
            msgs.append({"role": "tool", "tool_call_id": ids[j], "content": res["shown"]})
    elif r.get("type") == "note":
        msgs.append({"role": "user", "content": r["text"]})
assert orig is not None and not orig.get("final"), "нет хода N или он финальный"
out = open(f"{log[:-6]}_fork{N}.jsonl", "a")
seeds = [meta["seed"] + N - 1] + [1000 + k for k in range(K)]
for s in seeds:
    resp, err = F.chat(msgs, C.TEMP, s, meta["tool_schemas"])
    r, perr = F.parse_response(resp) if resp else (None, err)
    rec = {"seed": s, "orig": s == seeds[0], "error": err or (perr if not r else None)}
    if r:
        rec.update(content=r["content"], reasoning=r.get("reasoning"), usage=r["usage"],
                   calls=[c["function"] for c in r["calls"]])
        if s == seeds[0]:
            rec["same_as_log"] = (r["content"] == orig.get("content") and r.get("reasoning") == orig.get("reasoning"))
    out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
    print(s, rec.get("same_as_log", ""), (rec.get("content") or rec.get("error") or "")[:160].replace("\n", " "), flush=True)
