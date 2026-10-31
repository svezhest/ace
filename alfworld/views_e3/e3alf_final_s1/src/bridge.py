"""Bridge to the ALFWorld benchmark. Not part of the harness: do not edit.

The benchmark is the AgentBench ALFWorld task as published, run outside src/ (a black box: the game,
the task's rules, its turn limit and its check of success). The bridge only carries messages between
the harness and the task, the way an AgentBench agent talks to it:
  - start(): the task's first messages — its own system prompt and the opening message with the room,
    the goal and the valid actions;
  - send(reply): hands the task one reply of the model, as it is; returns the task's new messages —
    the environment's answer to the action (role "tool"), or the task's own message when the reply
    had no usable tool call (role "user");
  - finished, end: whether the task has ended the episode, and how: {"reason": "finished" | "step limit" |
    "error", "status": the task's own status, "detail": ...}.
Every reply handed to the task is a turn; the task allows STEP_LIMIT turns. Success is checked by
the benchmark after the episode; the agent never sees anything about it.
The model reaches the harness through guard(): the same reply REPEATS times in a row ends the episode
(end: "error", detail "repeated reply").
"""
STEP_LIMIT = 50  # turns (replies handed to the task) per episode


class Episode:
    def __init__(self, bench):
        self._bench = bench
        self.turns = 0
        self.finished = False
        self.end = None

    def _take(self, out):
        if out["finish"] and not self.finished:
            self.finished = True
            self.end = self._bench.end_of(out["status"])
        return out["messages"]

    def start(self):
        return self._take(self._bench.start())

    def send(self, reply):
        assert not self.finished, "the episode is over"
        self.turns += 1
        return self._take(self._bench.interact(reply))


REPEATS = 3  # the same model reply this many times in a row ends the episode (guard)


class Loop(Exception):
    """guard() ended the episode: the model sent the same reply REPEATS times in a row."""


def _same(m):
    calls = [(c["function"]["name"], c["function"]["arguments"]) for c in m.get("tool_calls") or []]
    return m.get("content"), calls


def guard(episode, llm):
    """The model as the harness gets it, with a crude guard of the stand (not part of the harness): before
    each call, if the model's last REPEATS replies in the conversation are the same, the episode ends with
    end = {"reason": "error", "detail": "repeated reply"} and Loop is raised."""
    def call(messages, *args, **kwargs):
        last = [_same(m) for m in messages if m.get("role") == "assistant"][-REPEATS:]
        if len(last) == REPEATS and all(x == last[0] for x in last):
            episode.finished = True
            episode.end = {"reason": "error", "detail": "repeated reply"}
            raise Loop()
        return llm(messages, *args, **kwargs)
    return call
