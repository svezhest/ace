"""Один эпизод ALFWorld: bridge.Episode (игра) + harness.run из src/ + llm.Client (транспорт). Данные — $ALFWORLD_DATA."""
import os
import time
import traceback

import bridge
import harness
from llm import Client, EpisodeEnd


def play(job):
    ep = bridge.Episode(job["task"], os.environ["ALFWORLD_DATA"])
    llm = Client(job["url"], job["model"], bridge.STEP_LIMIT, job["wall_limit"])
    t0, reason, detail, messages = time.time(), None, "", None
    try:
        messages = harness.run(ep, llm)
    except EpisodeEnd as e:
        reason, detail = e.reason, e.detail
    except Exception:
        reason, detail = "harness error", traceback.format_exc(limit=5)
    if not isinstance(messages, list):
        messages = llm.conversation or []
    if ep.won:
        reason = "success"
    elif reason is None:
        reason = ("repeated action" if ep.end_reason == "repeated action" else
                  "step limit" if len(llm.calls) >= bridge.STEP_LIMIT else "harness stopped early")
    hint = ep.hint(job["hint_level"]) if job["hint_level"] > 0 else None
    ep.close()
    return {"run": job["run"], "ok": reason == "success", "reason": reason, "hint": hint, "messages": messages,
            "meta": {"detail": detail, "sec": round(time.time() - t0, 1), "model_calls": len(llm.calls),
                     "max_prompt_tokens": max((c["prompt_tokens"] or 0 for c in llm.calls), default=0)}}
