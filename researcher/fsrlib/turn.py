"""Один ход: запрос к модели, запись хода, вызовы инструментов с приписками цикла."""
import json
import time

from . import cfg as C
from . import prompt as P
from . import model as M
from . import tools as TO


def ask(run, est):
    """Запрос с повторами при битом ответе API -> (ответ, сек, None) или (None, сек, причина конца)."""
    st, w = run.st, run.w
    t0 = time.time()
    r = perr = None
    for attempt in range(M.API_RETRIES + 1):
        resp, err = M.chat(run.messages, run.temp, run.seed + st["turns"], P.FINAL_TOOLS if run.final_left else P.TOOLS)
        if err:
            break
        r, perr = M.parse_response(resp)
        if r:
            break
        w({"type": "api_error", "turn": st["turns"] + 1, "attempt": attempt + 1, "error": perr,
           "response": json.dumps(resp, ensure_ascii=False)[:2000]})
        if attempt < M.API_RETRIES:
            st["api_retries"] += 1
            time.sleep(M.API_RETRY_SEC)
    dt = time.time() - t0
    st["model_sec"] += dt
    st["turns"] += 1
    st["final_turns"] += bool(run.final_left)
    if err:
        w({"type": "turn", "i": st["turns"], "sec": round(dt, 1), "error": err, "est_prompt": est})
        return None, dt, f"forced: model call failed: {err[:200]}"
    if not r:
        w({"type": "turn", "i": st["turns"], "sec": round(dt, 1), "error": f"bad response: {perr}",
           "est_prompt": est})
        return None, dt, f"forced: bad API response after {M.API_RETRIES + 1} attempts: {perr}"
    return r, dt, None


def reply(run, r, est, dt):
    """Ответ модели -> история и лог; вызовы по порядку до finish. -> (finish ли, причина конца или None)."""
    st = run.st
    u = r["usage"]
    run.last_prompt = (u.get("prompt_tokens") or est) + (u.get("completion_tokens") or 0)
    run.pending = 0
    st["gen_tokens"] += u.get("completion_tokens") or 0
    st["max_prompt"] = max(st["max_prompt"], u.get("prompt_tokens") or 0)
    if r["finish_reason"] == "length":
        st["length_stops"] += 1
    calls = r["calls"]
    rec = {"type": "turn", "i": st["turns"], "sec": round(dt, 1), "usage": u, "est_prompt": est,
           "final": bool(run.final_left), "finish_reason": r["finish_reason"], "content": r["content"], "reasoning": r.get("reasoning"),
           "tool_calls": [{"name": c["function"]["name"], "arguments": c["function"]["arguments"]} for c in calls],
           "results": []}
    if r["bad"]:
        rec["malformed_calls"] = r["bad"]
        st["bad_call"] += r["bad"]
    amsg = {"role": "assistant", "content": r["content"] or ""}
    if calls:
        amsg["tool_calls"] = [{"id": c["id"] or f"call_{st['turns']}_{j}", "type": "function",
                               "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}
                              for j, c in enumerate(calls)]
    run.messages.append(amsg)
    finished, end = False, None
    run.rejected_now = run.accepted_now = 0
    if not calls:
        end = _no_call(run, r, rec)
    for c in amsg.get("tool_calls", []):
        finished = _tool_call(run, c, r["content"], rec)
        if finished:
            break
    if calls:
        run.w(rec)
    return finished, end


def _no_call(run, r, rec):
    """Ответ без вызова -> подсказка модели; -> причина конца, если таких ответов слишком много."""
    st = run.st
    st["no_call"] += 1
    txt = r["content"] or ""
    kind = "malformed" if (r["bad"] or "<tool_call>" in txt or "<function=" in txt) else "none"
    note = ("Your reply contained a tool call the system could not parse. Call a tool again using the "
            "tool-calling format." if kind == "malformed" else
            "Your reply contained no tool call. Continue with bash, record findings with report, or call finish."
            if not run.final_left else "Your reply contained no tool call. Call report for each supported finding, then finish.")
    rec["format_fail"] = kind
    run.note_user(note)
    run.w(rec)
    if st["no_call"] >= 6 and not run.final_left:
        return "forced: too many replies without a tool call"
    return None


def _tool_call(run, c, said, rec):
    """Один вызов: исполнение, приписки, tool-сообщение в историю. -> finish ли."""
    st = run.st
    name_, raw = c["function"]["name"], c["function"]["arguments"]
    st["tool_calls"] += 1
    res = {"name": name_, "arguments": raw}
    out, finished = TO.call(run, name_, raw, res, said)
    run.since_report += 1
    if C.REPEAT_STOP and not res.get("repeat") and not res.get("say_rejected"):
        run.repeat_run = 0
    out = _notes(run, name_, out, finished)
    res["shown"] = out if res.get("output_head") != out else "(= output_head)"
    rec["results"].append(res)
    run.tool_meta[len(run.messages)] = (st["tool_calls"], _cmd_of(name_, raw))
    run.tool_msgs.append(len(run.messages))
    run.messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    run.pending += M.est_tokens(out) + 10
    return finished


def _notes(run, name_, out, finished):
    """Приписки цикла к выводу: контекст, шаги, давно не было report; список гипотез."""
    st = run.st
    left = C.STEP_BUDGET - st["tool_calls"]
    est_now = run.est() + M.est_tokens(out)
    if not finished and not run.final_left:
        if C.WARN_AT is not None and est_now >= C.WARN_AT and not run.warned_ctx:
            run.warned_ctx = True
            out += (f"\n\n[note: about {est_now} of {C.CTX} context tokens used. Start wrapping up: report the "
                    "findings you can support, then call finish.]")
        if left <= C.STEP_BUDGET - C.STEP_WARN and not run.warned_steps:
            run.warned_steps = True
            out += f"\n\n[note: {left} tool calls left. Report what you have found, then call finish.]"
        elif C.REMIND_EVERY and run.since_report and run.since_report % C.REMIND_EVERY == 0:
            st["reminders"] += 1
            bl = (f"{C.BASH_LIMIT - st['bash_calls']} of {C.BASH_LIMIT} bash calls" if C.BASH_LIMIT
                  else f"{left} of {C.STEP_BUDGET} calls")
            out += (f"\n\n[note: {run.since_report} calls since your last report; {bl} left. Record with report "
                    "what these outputs have shown about why runs fail, or a sharper version of an earlier "
                    "finding, together with your next command.]")
    if C.HYPOTHESES and run.hyps and name_ in ("bash", "runs") and not run.final_left:
        out += "\n\n[hypotheses: " + "; ".join(
            f"{x['id']} {x['result']}: {x['claim'][:110]}" for x in run.hyps[-8:]) + "]"
    return out


def _cmd_of(name_, raw):
    if name_ != "bash":
        return name_
    try:
        return json.loads(raw).get("command", "")
    except Exception:  # noqa: BLE001
        return ""
