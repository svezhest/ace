"""Один ход: запрос к модели, запись хода, ответ без вызова, вызовы инструментов по порядку до finish."""
import time

from . import cfg as C
from . import model as MO
from . import tools as TO
from . import phase as PH


def ask(run):
    """-> (ответ, запись хода для лога); сообщение ассистента — уже в истории."""
    t0 = time.time()
    r = MO.chat(run.messages, run.offered(), run.seed + run.turns)
    run.turns += 1
    u = r["usage"]
    run.est = (u.get("prompt_tokens") or run.est) + (u.get("completion_tokens") or 0)
    amsg = {"role": "assistant", "content": r["content"]}
    if r["calls"]:
        amsg["tool_calls"] = r["calls"]
    run.messages.append(amsg)
    rec = {"type": "turn", "i": run.turns, "sec": round(time.time() - t0, 1), "usage": u, "final": bool(run.final_left),
           "content": r["content"], "results": []}
    return r, rec


def no_call(run):
    """Ответ без вызова -> подсказка модели; причина конца, если таких ответов MAX_NO_CALL."""
    run.no_call += 1
    run.say(C.NO_CALL_MSG)
    return "forced: no tool calls" if run.no_call >= C.MAX_NO_CALL else None


def run_calls(run, calls, rec):
    """Вызовы по порядку; finish обрывает остальные -> был ли finish."""
    for c in calls:
        name, raw = c["function"]["name"], c["function"]["arguments"]
        out, ok, finished = TO.call(run, name, raw)
        if out != C.REPEAT_MSG:
            run.repeats = 0                  # повторы считаются подряд
        rec["results"].append({"name": name, "arguments": raw, "ok": ok, "out": out})
        run.messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
        run.est += MO.est_tokens(out) + 10
        if finished:
            return True
    return False


def turn(run):
    """Ход целиком -> причина конца сессии или None."""
    r, rec = ask(run)
    run.rejected = False
    end = None if r["calls"] else no_call(run)
    finished = run_calls(run, r["calls"], rec)
    run.w(rec)
    return end or PH.after_turn(run, finished)
