"""Stub models for tests: same interface as llm.Client (callable + .calls/.conversation/.requests)."""
import copy
import json
import re


def last_actions(messages):
    for m in reversed(messages):
        if m["role"] in ("user", "tool") and "AVAILABLE ACTIONS:" in (m.get("content") or ""):
            return m["content"].split("AVAILABLE ACTIONS:", 1)[1].strip().split("\n")
    return []


def tool_reply(action, i):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": f"call_{i}", "type": "function",
                            "function": {"name": "take_action", "arguments": json.dumps({"action": action})}}]}


class Fake:
    """script: list of items; str -> take_action(str); {"text": ...} -> plain text reply;
    {"args": ...} -> raw arguments string; "@first" -> first available action. Then repeats the last item."""

    def __init__(self, script, step_limit=50):
        self.script, self.step_limit = script, step_limit
        self.calls, self.requests, self.conversation = [], [], None

    def __call__(self, messages, tools):
        from llm import EpisodeEnd
        self.conversation = messages
        if len(self.calls) >= self.step_limit:
            raise EpisodeEnd("step limit")
        self.requests.append(copy.deepcopy(messages))
        i = len(self.calls)
        item = self.script[min(i, len(self.script) - 1)]
        self.calls.append({"sec": 0, "prompt_tokens": sum(len(m.get("content") or "") for m in messages) // 4,
                           "completion_tokens": 1, "finish_reason": "stop"})
        if item == "@first":
            return tool_reply(last_actions(messages)[0], i)
        if isinstance(item, dict) and "text" in item:
            return {"role": "assistant", "content": item["text"]}
        if isinstance(item, dict) and "args" in item:
            r = tool_reply("", i)
            r["tool_calls"][0]["function"]["arguments"] = item["args"]
            return r
        return tool_reply(item, i)
