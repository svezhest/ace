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
    {"args": ...} -> raw arguments string; {"role": "assistant", ...} -> this message as it is (replay of a log);
    "@first" -> first available action. Then repeats the last item."""

    def __init__(self, script, max_calls=1000):
        self.script, self.max_calls = script, max_calls
        self.calls, self.requests, self.outputs, self.conversation = [], [], [], None

    def __call__(self, messages, tools):
        out = self._reply(messages)
        self.outputs.append(copy.deepcopy(out))
        return out

    def _reply(self, messages):
        from llm import EpisodeEnd
        self.conversation = messages
        if len(self.calls) >= self.max_calls:
            raise EpisodeEnd("model error", "stub: no more calls")
        self.requests.append(copy.deepcopy(messages))
        i = len(self.calls)
        item = self.script[min(i, len(self.script) - 1)]
        self.calls.append({"sec": 0, "prompt_tokens": sum(len(m.get("content") or "") for m in messages) // 4,
                           "completion_tokens": 1, "finish_reason": "stop"})
        if isinstance(item, dict) and item.get("role") == "assistant":
            return copy.deepcopy(item)
        if item == "@first":
            return tool_reply(last_actions(messages)[0], i)
        if isinstance(item, dict) and "text" in item:
            return {"role": "assistant", "content": item["text"]}
        if isinstance(item, dict) and "args" in item:
            r = tool_reply("", i)
            r["tool_calls"][0]["function"]["arguments"] = item["args"]
            return r
        return tool_reply(item, i)
