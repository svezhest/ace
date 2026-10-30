"""Model transport for the harness (outside src/: the researcher does not see or edit it).

Mirrors the Harness-R1 rollout client (AgentBench HTTPAgent.inference_openai): T=0, max_tokens 4096,
tools passed as-is, 3 attempts on transport errors, context overflow ends the episode,
tool calls written as text in `content` are rescued into `tool_calls` (serving compatibility shim).
Also enforces the episode's wall clock, so that harness edits cannot exceed it (turns are counted by the task).
"""
import copy
import json
import re
import time
import uuid

import requests


class EpisodeEnd(Exception):
    def __init__(self, reason, detail=""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


CONTEXT_WORDS = (("prompt", "context", "tokens"),
                 ("limit", "exceed", "max", "long", "much", "many", "reach", "over", "up", "beyond"))


def is_context_error(text):
    t = text.lower()
    return all(any(w in t for w in group) for group in CONTEXT_WORDS)


TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S | re.I)


def _strip_fence(text):
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _payload_calls(payload, allowed):
    calls = []
    for item in payload if isinstance(payload, list) else [payload]:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("tool_name")
        args = item.get("arguments", item.get("parameters", {}))
        if isinstance(item.get("function"), dict):
            name = item["function"].get("name", name)
            args = item["function"].get("arguments", args)
        if not isinstance(name, str) or (allowed and name not in allowed):
            continue
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"value": args}
        calls.append({"id": "call_" + uuid.uuid4().hex[:24], "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
    return calls


def rescue_tool_calls(msg, tools):
    if msg.get("tool_calls") or not isinstance(msg.get("content"), str):
        return msg
    allowed = {t["function"]["name"] for t in tools or []}
    content = msg["content"]
    calls = []
    for block in TOOL_CALL_BLOCK.findall(content):
        try:
            calls += _payload_calls(json.loads(_strip_fence(block)), allowed)
        except Exception:
            pass
    if not calls:
        try:
            calls = _payload_calls(json.loads(_strip_fence(content)), allowed)
        except Exception:
            calls = []
    if calls:
        msg = dict(msg, tool_calls=calls)
    return msg


def clean(msg):
    out = {"role": "assistant", "content": msg.get("content")}
    if msg.get("tool_calls"):
        out["tool_calls"] = [{"id": c.get("id"), "type": c.get("type", "function"),
                              "function": {"name": c["function"].get("name"),
                                           "arguments": c["function"].get("arguments")}}
                             for c in msg["tool_calls"]]
    return out


class Client:
    """llm(messages, tools) -> assistant message. One instance per episode."""

    def __init__(self, url, model, wall_limit_s=3600, max_tokens=4096, http_timeout=900, temperature=0.0):
        self.url, self.model, self.temperature = url.rstrip("/") + "/chat/completions", model, temperature
        self.max_tokens, self.http_timeout = max_tokens, http_timeout
        self.deadline = time.time() + wall_limit_s
        self.conversation = None  # live reference to the harness's message list
        self.requests = []        # copies of what was sent, for the append-only check
        self.calls = []           # per call: seconds, prompt/completion tokens, finish reason
        self.outputs = []         # the replies returned, for the check that the task got only these

    def __call__(self, messages, tools):
        self.conversation = messages
        if time.time() > self.deadline:
            raise EpisodeEnd("timeout")
        body = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "temperature": self.temperature}
        if tools:
            body["tools"] = tools
        self.requests.append(copy.deepcopy(messages))
        last_err = ""
        for attempt in range(3):
            t0 = time.time()
            try:
                r = requests.post(self.url, json=body, timeout=self.http_timeout,
                                  headers={"Authorization": "Bearer x"})
            except Exception as e:
                last_err = repr(e)
            else:
                if r.status_code == 200:
                    data = r.json()
                    msg = clean(rescue_tool_calls(data["choices"][0]["message"], tools))
                    usage = data.get("usage") or {}
                    self.calls.append({"sec": round(time.time() - t0, 2),
                                       "prompt_tokens": usage.get("prompt_tokens"),
                                       "completion_tokens": usage.get("completion_tokens"),
                                       "finish_reason": data["choices"][0].get("finish_reason")})
                    self.outputs.append(copy.deepcopy(msg))
                    return msg
                if is_context_error(r.text):
                    raise EpisodeEnd("context exhausted", r.text[:300])
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            time.sleep(attempt + 2)
        raise EpisodeEnd("model error", last_err)
