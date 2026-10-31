"""Smoke test: runs src/harness.py and src/bridge.py with a stub task and a stub model (not the benchmark).

    python3 tests/smoke.py

Two scenarios: the stub task does not end the episode, and it ends it at turn 4. The stub knows nothing of
the real task: it answers every reply with a placeholder, as the bridge's contract allows. For each scenario
it prints how the run ended and what the harness added to the conversation after which model reply (model
replies and environment results are left out), or the error with its traceback. Nothing is written.
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
    """Stub of the task behind src/bridge.py, at the level of the bridge's contract: start() gives a system
    message and an opening message, every reply handed over is a turn and gets one message back (role "tool"
    when it has a tool call, role "user" when it has none), and the stub ends the episode at turn `ends_at`
    or at the limit. The texts are placeholders; nothing about the real task, its game or its rules."""

    def __init__(self, ends_at=None):
        self.ends_at, self.turns, self.status, self.results = ends_at, 0, "running", []

    def _out(self, messages):
        return {"messages": messages, "status": self.status, "finish": self.status != "running"}

    def start(self):
        return self._out([{"role": "system", "content": "(stub: the task's system message)"},
                          {"role": "user", "content": "(stub: the task's opening message)"}])

    def interact(self, reply):
        self.turns += 1
        calls = reply.get("tool_calls") or []
        if calls:
            text = f"(stub: the environment's answer to turn {self.turns})"
            self.results.append(text)
            out = [{"role": "tool", "tool_call_id": calls[0].get("id"), "content": text}]
        else:
            out = [{"role": "user", "content": f"(stub: the task's message to turn {self.turns}, a reply without a tool call)"}]
        if self.ends_at and self.turns >= self.ends_at:
            self.status = "ended"
        elif self.turns >= N_REPLIES:
            self.status = "limit"
        return self._out(out)

    def end_of(self, status):
        return {"reason": "step limit" if status == "limit" else "finished", "status": status}


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
    acts = [f"(stub action {k})" for k in range(1, N_REPLIES + 1)]
    return [("the stub task does not end the episode: 50 replies, each with a tool call", AlfTask, acts, alf_reply),
            ("the stub task ends the episode at turn 4", lambda: AlfTask(ends_at=4), acts, alf_reply)]


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
