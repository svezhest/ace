"""Stub model for tests and replays: same interface as llm.Client (callable + .calls/.conversation/.requests/.outputs)."""
import copy


class Fake:
    """script: list of reply texts (or assistant messages, as they are), then repeats the last one."""

    def __init__(self, script, max_calls=1000):
        self.script, self.max_calls = script, max_calls
        self.calls, self.requests, self.outputs, self.conversation = [], [], [], None

    def __call__(self, messages):
        from llm import EpisodeEnd
        self.conversation = messages
        if len(self.calls) >= self.max_calls:
            raise EpisodeEnd("model error", "stub: no more calls")
        self.requests.append(copy.deepcopy(messages))
        item = self.script[min(len(self.calls), len(self.script) - 1)]
        self.calls.append({"sec": 0, "prompt_tokens": sum(len(m.get("content") or "") for m in messages) // 4,
                           "completion_tokens": 1, "finish_reason": "stop"})
        out = copy.deepcopy(item) if isinstance(item, dict) else {"role": "assistant", "content": item}
        self.outputs.append(copy.deepcopy(out))
        return out
