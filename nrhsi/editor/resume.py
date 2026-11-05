"""Воскрешение сессии писателя (6.11): история из лога до хода I, ход I исполняется заново, bash добавлен.
Правки src/ из ходов < I повторяются на свежей копии; системный промпт и первое сообщение сверяются с логом."""
import json
import os

from . import turn as TU


def load(path):
    return [json.loads(line) for line in open(path)]


def apply_edits(recs, upto, root):
    """Применённые правки ходов < upto — на копию root (тем же заменой строки, что и edit)."""
    n = 0
    for r in recs:
        if r.get("type") != "turn" or r["i"] >= upto:
            continue
        for c, res in zip(r["tool_calls"], r["results"]):
            if c["name"] != "edit" or not (res.get("edit") or {}).get("applied"):
                continue
            a = json.loads(c["arguments"])
            p = f"{root}/{a['path']}"
            old = open(p).read() if os.path.exists(p) else ""
            assert a["old_string"] == "" or old.count(a["old_string"]) == 1, f"replay edit {r['i']}: old_string"
            new = a["new_string"] if a["old_string"] == "" else old.replace(a["old_string"], a["new_string"])
            open(p, "w").write(new)
            n += 1
    return n


def restorer(recs, upto, extra_bash):
    meta = recs[0]

    def restore(run):
        assert run.messages[0]["content"] == meta["system"], "system prompt differs from the log"
        assert run.messages[1]["content"] == meta["first_user"], "first message differs from the log"
        st = run.st
        for r in recs[1:]:
            if r.get("type") == "note":
                run.messages.append({"role": "user", "content": r["text"]})
            elif r.get("type") == "turn" and r["i"] < upto:
                amsg = {"role": "assistant", "content": r.get("content") or ""}
                if r["tool_calls"]:
                    amsg["tool_calls"] = [{"id": f"call_{r['i']}_{j}", "type": "function",
                                           "function": {"name": c["name"], "arguments": c["arguments"]}}
                                          for j, c in enumerate(r["tool_calls"])]
                run.messages.append(amsg)
                for j, res in enumerate(r["results"]):
                    run.messages.append({"role": "tool", "tool_call_id": f"call_{r['i']}_{j}", "content": res["shown"]})
                st["turns"] = r["i"]
                st["tool_calls"] += len(r["tool_calls"])
                st["bash_calls"] += sum(c["name"] == "bash" and "no longer available" not in str(res.get("shown"))
                                        for c, res in zip(r["tool_calls"], r["results"]))
            elif r.get("type") == "turn" and r["i"] == upto:
                break
        cut = next(r for r in recs if r.get("type") == "turn" and r["i"] == upto)
        # заметки между последним ходом < upto и ходом upto уже добавлены циклом (идут в логе до него)
        run.final_left, run.final_why = 0, None
        run.bash_limit = st["bash_calls"] + extra_bash
        run.w({"type": "resume", "from_turn": upto, "bash_used": st["bash_calls"], "bash_limit": run.bash_limit})
        st["turns"] = upto
        amsg = {"role": "assistant", "content": cut.get("content") or ""}
        amsg["tool_calls"] = [{"id": f"call_{upto}_{j}", "type": "function",
                               "function": {"name": c["name"], "arguments": c["arguments"]}}
                              for j, c in enumerate(cut["tool_calls"])]
        run.messages.append(amsg)
        rec = {"type": "turn", "i": upto, "replayed": True, "content": cut.get("content"),
               "tool_calls": cut["tool_calls"], "results": []}
        TU.run_calls(run, amsg, rec)
        run.w(rec)
        run.note_user(f"bash is available again: {run.bash_limit - st['bash_calls']} more calls.")
    return restore
