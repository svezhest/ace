"""Один ход: запрос к модели (повторы при битом ответе API), запись хода, ответ без вызова, вызовы инструментов."""
import time
import traceback

from .cfg import F
from . import cfg as C
from . import tools as TO
from . import phase as PH


def ask(run):
    """-> (ответ, сек, None) или (None, сек, причина конца)."""
    st = run.st
    t0 = time.time()
    r = perr = err = None
    for attempt in range(F.API_RETRIES + 1):
        resp, err = F.chat(run.messages, F.TEMP, run.seed + st["turns"], run.offered())
        if err:
            break
        r, perr = F.parse_response(resp)
        if r:
            break
        run.w({"type": "api_error", "attempt": attempt + 1, "error": perr})
        time.sleep(F.API_RETRY_SEC)
    dt = time.time() - t0
    st["model_sec"] += dt
    st["turns"] += 1
    st["final_turns"] += bool(run.final_left)
    if err or not r:
        run.w({"type": "turn", "i": st["turns"], "error": err or perr})
        return None, dt, f"forced: model call failed: {(err or perr)[:200]}"
    return r, dt, None


def account(run, r, est):
    """Учёт токенов по usage ответа."""
    st, u = run.st, r["usage"]
    run.last_prompt = (u.get("prompt_tokens") or est) + (u.get("completion_tokens") or 0)
    run.pending = 0
    st["max_prompt"] = max(st["max_prompt"], u.get("prompt_tokens") or 0)
    st["gen_tokens"] += u.get("completion_tokens") or 0
    st["length_stops"] += r["finish_reason"] == "length"


def record(run, r, dt):
    """-> (запись хода для лога, сообщение ассистента — уже в истории)."""
    st, calls = run.st, r["calls"]
    rec = {"type": "turn", "i": st["turns"], "sec": round(dt, 1), "usage": r["usage"], "final": bool(run.final_left),
           "finish_reason": r["finish_reason"], "content": r["content"], "reasoning": r.get("reasoning"),
           "tool_calls": [{"name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                          for c in calls], "results": []}
    amsg = {"role": "assistant", "content": r["content"] or ""}
    if calls:
        amsg["tool_calls"] = [{"id": c["id"] or f"call_{st['turns']}_{j}", "type": "function",
                               "function": c["function"]} for j, c in enumerate(calls)]
    run.messages.append(amsg)
    return rec, amsg


def no_call(run, r, rec):
    """Ответ без вызова инструмента -> причина конца или None."""
    st = run.st
    st["no_call"] += 1
    txt = r["content"] or ""
    malformed = r["bad"] or "<tool_call>" in txt or "<function=" in txt
    run.w(rec)
    run.note_user("Your reply contained a tool call the system could not parse. Call a tool again using the "
                  "tool-calling format." if malformed else
                  "Your reply contained no tool call. Continue with the tools; call finish when you are done.")
    return "forced: too many replies without a tool call" if st["no_call"] >= C.MAX_NO_CALL else None


def run_calls(run, amsg, rec):
    """Вызовы ответа по порядку; finish обрывает остальные -> был ли finish."""
    finished = False
    for c in amsg.get("tool_calls", []):
        run.st["tool_calls"] += 1
        res = {"name": c["function"]["name"]}
        try:
            out, finished = TO.do_call(run, c["function"]["name"], c["function"]["arguments"], res)
        except Exception as e:  # noqa: BLE001
            res["harness_error"] = traceback.format_exc()[-2000:]
            out, finished = f"Error: {type(e).__name__}: {str(e)[:300]}", False
        res["shown"] = out
        rec["results"].append(res)
        run.messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
        run.pending += F.est_tokens(out) + 10
        if finished:
            break
    return finished


def turn(run, est):
    """Ход целиком -> причина конца сессии или None."""
    r, dt, end = ask(run)
    if end:
        return end
    account(run, r, est)
    rec, amsg = record(run, r, dt)
    end = None if r["calls"] else no_call(run, r, rec)
    finished = run_calls(run, amsg, rec)
    if r["calls"]:
        run.w(rec)
    return end or PH.after_turn(run, finished)
