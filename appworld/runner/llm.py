"""Model transport for the harness (outside src/: the researcher does not see or edit it).

Mirrors AppWorld's LanguageModel as configured for the ReAct agent (openai client, chat completions):
body = model, messages, temperature 0, seed 100; no max_tokens, no tools. Transport errors
(connection, 429, 5xx) are retried 3 times 15 s apart; a 4xx ends the episode (upstream BREAKING_ERROR),
as "context exhausted" when it is about the context window. A reply wrapped in <think>...</think> is split
into reasoning_content + content (upstream maybe_insert_reasoning_content).
Also enforces the episode's wall clock and per-call time, so that harness edits cannot exceed them
(steps are counted by the benchmark's loop).
"""
import copy
import re
import time

import requests


class EpisodeEnd(Exception):
    def __init__(self, reason, detail=""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


CONTEXT_WORDS = (("prompt", "context", "tokens"),
                 ("limit", "exceed", "max", "long", "much", "many", "reach", "over", "up", "beyond"))
THINK = re.compile(r"<(?:think|thinking)>(.*?)</(?:think|thinking)>(.*)", re.DOTALL)


def is_context_error(text):
    t = text.lower()
    return all(any(w in t for w in group) for group in CONTEXT_WORDS)


def clean(msg):
    out = {"role": "assistant", "content": msg.get("content")}
    reasoning = None
    if "reasoning_content" in msg:
        reasoning = msg["reasoning_content"]
    elif "reasoning" in msg:
        reasoning = msg["reasoning"]
    elif out["content"]:
        m = THINK.match(out["content"])
        if m:
            reasoning, out["content"] = m.group(1), m.group(2)
    if reasoning is not None:
        out["reasoning_content"] = reasoning
    return out


class Client:
    """llm(messages) -> assistant message. One instance per episode."""

    def __init__(self, url, model, wall_limit_s=3600, call_timeout_s=600, seed=100, temperature=0.0,
                 max_tokens=None):
        self.url, self.model, self.seed = url.rstrip("/") + "/chat/completions", model, seed
        self.temperature, self.max_tokens = temperature, max_tokens
        self.call_timeout = call_timeout_s
        self.deadline = time.time() + wall_limit_s
        self.conversation = None  # live reference to the harness's message list
        self.requests = []        # copies of what was sent, for the append-only check
        self.calls = []           # per call: seconds, prompt/completion tokens, finish reason
        self.outputs = []         # the replies as returned, for the check that the benchmark ran only their code

    def __call__(self, messages):
        self.conversation = messages
        if time.time() > self.deadline:
            raise EpisodeEnd("timeout")
        body = {"model": self.model, "messages": messages, "temperature": self.temperature, "seed": self.seed}
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        self.requests.append(copy.deepcopy(messages))
        last_err = ""
        for attempt in range(3):
            t0 = time.time()
            try:
                r = requests.post(self.url, json=body, timeout=(5, self.call_timeout),
                                  headers={"Authorization": "Bearer x"})
            except requests.Timeout as e:
                if isinstance(e, requests.ReadTimeout):
                    raise EpisodeEnd("timeout", f"model call over {self.call_timeout} s")
                last_err = repr(e)
            except Exception as e:
                last_err = repr(e)
            else:
                if r.status_code == 200:
                    data = r.json()
                    usage = data.get("usage") or {}
                    self.calls.append({"sec": round(time.time() - t0, 2),
                                       "prompt_tokens": usage.get("prompt_tokens"),
                                       "completion_tokens": usage.get("completion_tokens"),
                                       "finish_reason": data["choices"][0].get("finish_reason")})
                    msg = clean(data["choices"][0]["message"])
                    self.outputs.append(copy.deepcopy(msg))
                    return msg
                if is_context_error(r.text):
                    raise EpisodeEnd("context exhausted", r.text[:300])
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    raise EpisodeEnd("model error", f"HTTP {r.status_code}: {r.text[:300]}")
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            if attempt < 2:
                time.sleep(15)
        raise EpisodeEnd("model error", last_err)
