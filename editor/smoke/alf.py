"""Smoke test: runs src/harness.py with a stub environment and a stub model (not the benchmark).

    python3 tests/smoke.py

Two scenarios: a task that is never solved and a task that is solved. For each it prints how the run ended and
what the harness added to the conversation after which model reply (model replies and environment results are
left out), or the error with its traceback. Nothing is written.
"""
import os
import sys
import traceback

N_REPLIES = 50          # model replies per episode (STEP_LIMIT in src/bridge.py)
SHOW = 160


class StubStop(Exception):
    pass


# ---------------------------------------------------------------- stub environment and model

class AlfEpisode:
    """A room with five places; the goal is to put mug 1 in cabinet 1. The episode ends as in src/bridge.py:
    on success, or when the same raw action is sent 3 times in a row."""
    PLACES = ["cabinet 1", "countertop 1", "drawer 1", "fridge 1", "shelf 1"]
    GOAL = "put mug 1 in/on cabinet 1"

    def __init__(self):
        self.observation, self.admissible = "", []
        self.done = self.won = False
        self.end_reason = None
        self._sent, self.at, self.holding = [], None, False
        self.results = []

    def _acts(self):
        a = [f"go to {p}" for p in self.PLACES if p != self.at] + ["inventory", "look"]
        if self.at == "countertop 1" and not self.holding:
            a.append("take mug 1 from countertop 1")
        if self.at == "cabinet 1" and self.holding:
            a.append(self.GOAL)
        return a

    def _text(self):
        return self.observation + " AVAILABLE ACTIONS: " + "\n".join(self.admissible) + "\n"

    def reset(self):
        self.observation = ("You are in the middle of a room. Looking quickly around you, you see a cabinet 1, a "
                            "countertop 1, a drawer 1, a fridge 1, and a shelf 1.\n\nYour task is to: put a mug in "
                            "cabinet 1.")
        self.admissible = self._acts()
        return "Here is your task. " + self._text()

    def match(self, raw):
        r = str(raw).strip().lower()
        return r if r in self.admissible else self.admissible[0]

    def step(self, action, raw):
        if action.startswith("go to "):
            self.at = action[6:]
            self.observation = f"On the {self.at}, you see " + ("a mug 1." if self.at == "countertop 1" and not self.holding else "nothing.")
        elif action.startswith("take mug"):
            self.holding, self.observation = True, "You pick up the mug 1 from the countertop 1."
        elif action == self.GOAL:
            self.holding, self.won = False, True
            self.observation = "You put the mug 1 in/on the cabinet 1."
        elif action == "inventory":
            self.observation = "You are carrying: a mug 1." if self.holding else "You are not carrying anything."
        else:
            self.observation = f"You are facing the {self.at or 'middle of the room'}."
        self.admissible = self._acts()
        self._sent.append(raw)
        if len(self._sent) > 3 and len(set(self._sent[-3:])) == 1:
            self.done, self.won, self.end_reason = True, False, "repeated action"
        elif self.won:
            self.done, self.end_reason = True, "success"
        out = self._text()
        self.results.append(out)
        return out


def alf_reply(i, item):
    import json
    if isinstance(item, dict):
        if "text" in item:
            return {"role": "assistant", "content": item["text"]}
        args = item["args"]
    else:
        args = json.dumps({"action": item})
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"call_{i}", "type": "function", "function": {"name": "take_action", "arguments": args}}]}


def scenarios():
    cycle = ["go to drawer 1", "go to fridge 1", "look", "go to shelf 1", "inventory", "go to countertop 1"]
    fail = [cycle[i % len(cycle)] for i in range(N_REPLIES)]
    fail[2] = {"text": "I will look around first."}
    fail[3] = {"args": "not json"}
    fail[19] = fail[20] = "look"
    fail[21] = "go to drawer 1"
    win = ["go to countertop 1", "take mug 1 from countertop 1", "go to cabinet 1", AlfEpisode.GOAL]
    return [("the task is not solved: 50 replies with different actions, except reply 3 (text without a tool call), "
             "reply 4 (a tool call with broken arguments) and replies 20-21 (the same action twice)",
             AlfEpisode, fail, alf_reply),
            ("the task is solved at reply 4", AlfEpisode, win, alf_reply)]


# ---------------------------------------------------------------- run

def short(t):
    t = " ".join(str(t).split())
    return t if len(t) <= SHOW else t[:SHOW] + f"... [{len(t)} chars]"


def play(harness, Ep, script, mk):
    ep = Ep()
    marks = []                                       # len(messages) at each model call
    convo = {}

    def llm(messages, tools=None):
        convo["m"] = messages
        if len(marks) >= N_REPLIES:
            raise StubStop()
        marks.append(len(messages))
        i = len(marks) - 1
        return mk(i, script[min(i, len(script) - 1)])

    err = None
    try:
        msgs = harness.run(ep, llm)
        end = f"run() returned after {len(marks)} model replies"
    except StubStop:
        msgs, end = convo.get("m") or [], f"stopped at the step limit: {N_REPLIES} model replies"
    except BaseException:                            # noqa: BLE001
        msgs, end = convo.get("m") or [], f"crashed after {len(marks)} model replies"
        e = sys.exc_info()
        tb = [f for f in traceback.extract_tb(e[2]) if f.filename != __file__]   # only the harness frames
        err = "Traceback (most recent call last):\n" + "".join(traceback.format_list(tb)) + \
            "".join(traceback.format_exception_only(e[0], e[1]))
    return ep, msgs, marks, end, err


def report(msgs, marks, ep):
    """What the harness added (besides model replies and environment results), grouped by reply."""
    lines = []
    head = marks[0] if marks else len(msgs)
    roles = {}
    for m in msgs[:head]:
        roles[m.get("role")] = roles.get(m.get("role"), 0) + 1
    lines.append(f"  before reply 1: {head} messages (" + ", ".join(f"{k} {v}" for k, v in roles.items()) + ")")
    for m in msgs[:head]:
        if m.get("role") == "system":
            lines.append(f"    system: {short(m.get('content'))}")
    if head:
        lines.append(f"    last: {m.get('role')}: {short(msgs[head - 1].get('content'))}")
    results = set(ep.results)
    groups = []                                       # [(first, last, texts)]
    bounds = marks + [len(msgs)]
    for k in range(len(marks)):
        texts = []
        for m in msgs[bounds[k]:bounds[k + 1]][1:]:   # [0] is the model reply
            c = m.get("content") or ""
            if m.get("role") == "tool" and c in results:
                continue
            if c.startswith("Output:") and any(r in c for r in results):
                continue
            texts.append(f"{m.get('role')}: {short(c)}")
        if groups and groups[-1][2] == texts:
            groups[-1][1] = k
        else:
            groups.append([k, k, texts])
    for a, b, texts in groups:
        if not texts:
            continue
        when = f"after reply {a + 1}" if a == b else f"after each of replies {a + 1}-{b + 1} ({b - a + 1} times)"
        if b == len(marks) - 1:
            when += " (the last reply: run() returned, the model never reads this)"
        for t in texts:
            lines.append(f"  {when}: {t}")
    if not any(t for _, _, t in groups):
        lines.append("  after the replies: nothing besides the environment results")
    return lines


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
    print("smoke: src/harness.py with a stub environment and a stub model, not the benchmark. It shows what the "
          "harness adds to the conversation and when; model replies and environment results are left out.")
    try:
        import harness
    except BaseException:                            # noqa: BLE001
        print("import of src/harness.py failed:")
        print(traceback.format_exc(limit=-3))
        return
    for n, (desc, Ep, script, mk) in enumerate(scenarios(), 1):
        ep, msgs, marks, end, err = play(harness, Ep, script, mk)
        print(f"\n== scenario {n}: {desc}")
        print(f"  {end}; episode done: {bool(ep.done)}")
        if err:
            print("  " + "\n  ".join(err.rstrip().splitlines()[-8:]))
        for line in report(msgs, marks, ep):
            print(line)


if __name__ == "__main__":
    main()
