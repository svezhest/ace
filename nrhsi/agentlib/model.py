"""Вызов модели (OpenAI-совместимый API) и оценка токенов."""
import json
import time
import urllib.error
import urllib.request

from . import cfg as C


def chat(messages, tools, seed):
    body = {"model": C.MODEL, "messages": messages, "temperature": C.TEMP, "seed": seed, "max_tokens": C.MAX_GEN,
            "tools": tools}
    req = urllib.request.Request(C.URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                resp = json.load(r)
            ch = resp["choices"][0]
            msg = ch["message"]
            calls = [{"id": c.get("id") or f"call_{seed}_{i}", "type": "function",
                      "function": {"name": c["function"]["name"], "arguments": c["function"].get("arguments") or ""}}
                     for i, c in enumerate(msg.get("tool_calls") or []) if c.get("function", {}).get("name")]
            return {"content": msg.get("content") or "", "calls": calls, "usage": resp.get("usage") or {},
                    "finish_reason": ch.get("finish_reason")}
        except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
            time.sleep(5)
    raise RuntimeError(f"model call failed: {err}")


def est_tokens(text):
    return int(len(text) / 3.0) + 8
