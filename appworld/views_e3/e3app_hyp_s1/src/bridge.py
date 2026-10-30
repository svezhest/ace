"""Bridge to the AppWorld benchmark. Not part of the harness: do not edit.

This is the only place that knows the benchmark. The benchmark runs as a separate process (a black
box): AppWorld's own agent loop as published, with the harness as the agent; the bridge only carries
the harness's requests to it:
  - fill(text): renders `text` as a Jinja2 template with this task's values and returns it.
    The variables (slots) are fixed by the benchmark:
      {{ instruction }}                  the task, in the supervisor's words
      {{ main_user.first_name }}, {{ main_user.last_name }}, {{ main_user.email }},
      {{ main_user.phone_number }}       the supervisor, on whose behalf the agent works
      {{ app_descriptions }}             the apps of this task with their descriptions, as JSON
    Their values are available to the harness only through fill().
  - execute(code): the loop runs Python code in the task's REPL, where `apis` gives access to the apps;
    variables persist between calls. Returns what the code printed, or the error. Every call is a step;
    the loop allows STEP_LIMIT steps and ends the episode when the task has been marked complete (the
    code called apis.supervisor.complete_task).
  - finished, end: whether the loop has ended the episode, and how: {"reason": "finished" | "step limit" |
    "error", ...}.

Success is checked by the benchmark after the episode; the agent never sees anything about it.
"""
import json
import urllib.request

STEP_LIMIT = 50  # steps (calls of execute) per episode


class Episode:
    def __init__(self, url):
        self.url = url.rstrip("/")
        self.steps = 0
        self.finished = False
        self.end = None
        self._call("/start", {})

    def _call(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read())

    def fill(self, text):
        return self._call("/fill", {"text": text})

    def execute(self, code):
        assert not self.finished, "the episode is over"
        out = self._call("/execute", {"code": code})
        self.steps += 1
        if out["finish"]:
            self.finished = True
            self.end = {k: v for k, v in out["end"].items() if k != "steps"}
        return out["output"]
