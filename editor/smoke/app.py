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

class AppEpisode:
    """A stub REPL: the same code gives the same output; complete_task marks the task complete."""
    SLOTS = {"instruction": "Find the stub value and report it.", "main_user.first_name": "Sam",
             "main_user.last_name": "Stub", "main_user.email": "sam@stub.example",
             "main_user.phone_number": "5550100", "app_descriptions": '{"supervisor": "stub app"}'}

    def __init__(self):
        self._done = False
        self.results = []

    def fill(self, text):
        import re
        return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", lambda m: self.SLOTS.get(m.group(1), m.group(0)), text)

    def execute(self, code):
        if "complete_task" in code:
            self._done = True
            out = "Execution successful."
        elif not code.strip():
            out = ""
        else:
            out = "stub output: " + str(abs(hash(code)) % 10 ** 6)
        self.results.append(out)
        return out

    @property
    def done(self):
        return self._done


def app_reply(i, item):
    return {"role": "assistant", "content": item}


def scenarios():
    code = lambda c: "Next step.\n```python\n" + c + "\n```"                      # noqa: E731
    fail = [code(f"print({i + 1})") for i in range(N_REPLIES)]
    fail[2] = "Let me think about it first."
    for i in range(19, 24):
        fail[i] = code('print("same")')
    win = [code(f"print({i + 1})") for i in range(4)] + [code('apis.supervisor.complete_task(answer="stub")')]
    return [("the task is not solved: 50 replies with different code, except reply 3 (text without code) and replies "
             "20-24 (the same code, so the same output, five times)", AppEpisode, fail, app_reply),
            ("the task is solved at reply 5 (complete_task)", AppEpisode, win, app_reply)]


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
        print(f"  {end}; episode done: {bool(ep.done)}" + (f" ({ep.end_reason})" if getattr(ep, "end_reason", None) else ""))
        if err:
            print("  " + "\n  ".join(err.rstrip().splitlines()[-8:]))
        for line in report(msgs, marks, ep):
            print(line)


if __name__ == "__main__":
    main()
