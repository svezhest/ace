"""Smoke test: runs src/harness.py and src/bridge.py with a stub task and a stub model (not the benchmark).

    python3 tests/smoke.py

Two scenarios: a task that is never solved and a task that is solved. For each it prints how the run ended and
what the harness added to the conversation after which model reply (model replies and environment results are
left out), or the error with its traceback. Nothing is written.
"""
import os
import sys
import traceback

N_REPLIES = 50          # turns per episode (STEP_LIMIT in src/bridge.py)
MAX_CALLS = 200         # the stub model stops here if the task has not ended the episode
SHOW = 160


class StubStop(Exception):
    pass


# ---------------------------------------------------------------- stub task and model

class AlfTask:
    """Stub of the task behind src/bridge.py: what the AgentBench task returns (messages, status, finish)."""
    PLACES = ["cabinet 1", "countertop 1", "drawer 1", "fridge 1", "shelf 1"]
    GOAL = "put mug 1 in/on cabinet 1"

    def __init__(self):
        self.observation, self.admissible = "", []
        self._sent, self.at, self.holding, self.turns = [], None, False, 0
        self.status, self.results = "running", []

    def _acts(self):
        a = [f"go to {p}" for p in self.PLACES if p != self.at] + ["inventory", "look"]
        if self.at == "countertop 1" and not self.holding:
            a.append("take mug 1 from countertop 1")
        if self.at == "cabinet 1" and self.holding:
            a.append(self.GOAL)
        return a

    def _text(self):
        return self.observation + " AVAILABLE ACTIONS: " + "\n".join(self.admissible) + "\n"

    def _out(self, messages):
        return {"messages": messages, "status": self.status, "finish": self.status != "running"}

    def start(self):
        self.observation = ("You are in the middle of a room. Looking quickly around you, you see a cabinet 1, a "
                            "countertop 1, a drawer 1, a fridge 1, and a shelf 1.\n\nYour task is to: put a mug in "
                            "cabinet 1.")
        self.admissible = self._acts()
        return self._out([{"role": "system", "content": "(the task's system prompt)"},
                          {"role": "user", "content": "Here is your task. " + self._text()}])

    def interact(self, reply):
        import json
        self.turns += 1
        calls = reply.get("tool_calls") or []
        out = []
        if not calls:
            out.append({"role": "user", "content": "No executable tool calls found. Please call a tool instead"})
        else:
            try:
                raw = list(json.loads(calls[0]["function"]["arguments"]).values())[0]
            except Exception:  # noqa: BLE001
                raw = None
            if raw is None:
                out.append({"role": "user", "content": "No valid tool calls found. Please call a tool instead."})
            else:
                r = str(raw).strip().lower()
                self._step(r if r in self.admissible else self.admissible[0])
                text = self._text()
                self.results.append(text)
                out.append({"role": "tool", "tool_call_id": calls[0]["id"], "content": text})
                self._sent.append(raw)
                if len(self._sent) > 3 and len(set(self._sent[-3:])) == 1:
                    self.status = "agent invalid action"
        if self.status == "running" and self.turns >= N_REPLIES:
            self.status = "task limit reached"
        return self._out(out)

    def _step(self, action):
        if action.startswith("go to "):
            self.at = action[6:]
            self.observation = f"On the {self.at}, you see " + ("a mug 1." if self.at == "countertop 1" and not self.holding else "nothing.")
        elif action.startswith("take mug"):
            self.holding, self.observation = True, "You pick up the mug 1 from the countertop 1."
        elif action == self.GOAL:
            self.holding, self.status = False, "completed"
            self.observation = "You put the mug 1 in/on the cabinet 1."
        elif action == "inventory":
            self.observation = "You are carrying: a mug 1." if self.holding else "You are not carrying anything."
        else:
            self.observation = f"You are facing the {self.at or 'middle of the room'}."
        self.admissible = self._acts()

    def end_of(self, status):
        if status == "agent invalid action":
            return {"reason": "error", "status": status, "detail": "repeated action"}
        return {"reason": "step limit" if status == "task limit reached" else "finished", "status": status}


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
    win = ["go to countertop 1", "take mug 1 from countertop 1", "go to cabinet 1", AlfTask.GOAL]
    return [("the task is not solved: 50 replies with ordinary actions", AlfTask, fail, alf_reply),
            ("the task is solved at reply 4", AlfTask, win, alf_reply)]


# ---------------------------------------------------------------- run

def short(t):
    t = " ".join(str(t).split())
    return t if len(t) <= SHOW else t[:SHOW] + f"... [{len(t)} chars]"


def play(harness, Ep, script, mk):
    import bridge
    task = Ep()
    ep = bridge.Episode(task)
    marks = []                                       # len(messages) at each model call
    convo = {}

    def llm(messages, tools=None):
        convo["m"] = messages
        if len(marks) >= MAX_CALLS:
            raise StubStop()
        marks.append(len(messages))
        i = len(marks) - 1
        return mk(i, script[min(i, len(script) - 1)])

    err = None
    try:
        msgs = harness.run(ep, llm)
        end = f"run() returned after {len(marks)} model replies"
    except StubStop:
        msgs, end = convo.get("m") or [], f"stopped: {MAX_CALLS} model replies and the task has not ended the episode"
    except BaseException:                            # noqa: BLE001
        msgs, end = convo.get("m") or [], f"crashed after {len(marks)} model replies"
        e = sys.exc_info()
        tb = [f for f in traceback.extract_tb(e[2]) if f.filename != __file__]   # only the harness frames
        err = "Traceback (most recent call last):\n" + "".join(traceback.format_list(tb)) + \
            "".join(traceback.format_exception_only(e[0], e[1]))
    return ep, task, msgs, marks, end, err


def report(msgs, marks, task):
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
    results = set(task.results)
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
        for t in texts:
            lines.append(f"  {when}: {t}")
    if not any(t for _, _, t in groups):
        lines.append("  after the replies: nothing besides the environment results")
    return lines


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
    print("smoke: src/harness.py and src/bridge.py with a stub task and a stub model, not the benchmark. It shows what the "
          "harness adds to the conversation and when; model replies and environment results are left out.")
    try:
        import harness
    except BaseException:                            # noqa: BLE001
        print("import of src/harness.py failed:")
        print(traceback.format_exc(limit=-3))
        return
    for n, (desc, Ep, script, mk) in enumerate(scenarios(), 1):
        ep, task, msgs, marks, end, err = play(harness, Ep, script, mk)
        print(f"\n== scenario {n}: {desc}")
        print(f"  {end}; turns handed to the task: {ep.turns}; episode ended by the task: {bool(ep.finished)}"
              + (f" ({ep.end})" if ep.end else ""))
        if err:
            print("  " + "\n  ".join(err.rstrip().splitlines()[-8:]))
        for line in report(msgs, marks, task):
            print(line)


if __name__ == "__main__":
    main()
