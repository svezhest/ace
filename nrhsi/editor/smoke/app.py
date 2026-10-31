"""Smoke test: runs src/harness.py with a stub of the bridge and benchmark and a stub model (not the benchmark).

    python3 tests/smoke.py

Two scenarios: 50 replies with different code, and complete_task at reply 5. The stub knows nothing of the
real benchmark: it answers every step with a placeholder, as the bridge's contract allows. For each scenario it
prints how the run ended and what the harness added to the conversation after which model reply (model replies
and environment results are left out), or the error with its traceback. Nothing is written.
"""
import os
import sys
import traceback

N_REPLIES = 50          # steps per episode (STEP_LIMIT in src/bridge.py)
MAX_CALLS = 200         # the stub model stops here if the episode has not ended
SHOW = 160


class StubStop(Exception):
    pass


# ---------------------------------------------------------------- stub benchmark and model

class AppEpisode:
    """Stub of src/bridge.py's Episode at the level of its contract (fill, execute, steps, finished, end): fill puts
    placeholder values into the slots, every execute is a step and returns a placeholder, and the episode ends on
    complete_task or at the limit, as src/bridge.py says. Nothing about the real benchmark's apps or outputs."""
    SLOTS = {"instruction": "(stub: the task)", "main_user.first_name": "(stub: first name)",
             "main_user.last_name": "(stub: last name)", "main_user.email": "(stub: email)",
             "main_user.phone_number": "(stub: phone number)", "app_descriptions": "(stub: the apps)"}

    def __init__(self):
        self.steps, self.finished, self.end = 0, False, None
        self.results = []

    def fill(self, text):
        import re
        return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", lambda m: self.SLOTS.get(m.group(1), m.group(0)), text)

    def execute(self, code):
        assert not self.finished, "the episode is over"
        self.steps += 1
        out = f"(stub: what the code of step {self.steps} printed)"
        if "apis.supervisor.complete_task" in code:   # src/bridge.py: the loop ends the episode on complete_task
            self.finished, self.end = True, {"reason": "finished"}
        if not self.finished and self.steps >= N_REPLIES:
            self.finished, self.end = True, {"reason": "step limit"}
        self.results.append(out)
        return out


def app_reply(i, item):
    return {"role": "assistant", "content": item}


def scenarios():
    code = lambda c: "Next step.\n```python\n" + c + "\n```"                      # noqa: E731
    fail = [code(f"print({i + 1})") for i in range(N_REPLIES)]
    win = [code(f"print({i + 1})") for i in range(4)] + [code('apis.supervisor.complete_task(answer="stub")')]
    return [("50 replies with different code, no complete_task", AppEpisode, fail, app_reply),
            ("complete_task at reply 5", AppEpisode, win, app_reply)]


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
        msgs, end = convo.get("m") or [], f"stopped: {MAX_CALLS} model replies and the episode has not ended"
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
        for t in texts:
            lines.append(f"  {when}: {t}")
    if not any(t for _, _, t in groups):
        lines.append("  after the replies: nothing besides the environment results")
    return lines


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
    print("smoke: src/harness.py with a stub of the bridge and benchmark and a stub model, not the benchmark. It shows what the "
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
        print(f"  {end}; steps run: {ep.steps}; episode ended by the benchmark: {bool(ep.finished)}"
              + (f" ({ep.end})" if ep.end else ""))
        if err:
            print("  " + "\n  ".join(err.rstrip().splitlines()[-8:]))
        for line in report(msgs, marks, ep):
            print(line)


if __name__ == "__main__":
    main()
