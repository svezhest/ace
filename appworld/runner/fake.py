"""Stub model for tests and replays: same interface as llm.Client (callable + .calls/.conversation/.requests)."""
import copy


class Fake:
    """script: list of reply texts, then repeats the last one."""

    def __init__(self, script, step_limit=50):
        self.script, self.step_limit = script, step_limit
        self.calls, self.requests, self.conversation = [], [], None

    def __call__(self, messages):
        from llm import EpisodeEnd
        self.conversation = messages
        if len(self.calls) >= self.step_limit:
            raise EpisodeEnd("step limit")
        self.requests.append(copy.deepcopy(messages))
        item = self.script[min(len(self.calls), len(self.script) - 1)]
        self.calls.append({"sec": 0, "prompt_tokens": sum(len(m.get("content") or "") for m in messages) // 4,
                           "completion_tokens": 1, "finish_reason": "stop"})
        return {"role": "assistant", "content": item}
