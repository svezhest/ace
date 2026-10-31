"""One AppWorld task as a local HTTP service: the black box behind src/bridge.py.

Runs in AppWorld's own venv, one process per episode. The episode is AppWorld's own agent loop as
published (appworld repo, experiments/code/simplified/agent.py: Agent.solve_tasks for this one task),
with the harness as the agent. Fixture, and nothing else: HarnessAgent(Agent) —
  next_execution_inputs_usage_and_status  hands the last output to the harness, returns the code the
                                          harness sends (one ExecutionIO; no usage); a stop of the harness
                                          is Status(failed=True);
  log_usage                               also keeps world.task_completed(), the loop's own check right after;
parameters as in the experiment config (experiments/configs/ornith9b_react_dev.jsonnet): max_steps 50,
appworld_config {random_seed 100, raise_on_extra_parameters true}, usage limits, logger.
  /start     solve_tasks([task_id]) (in the main thread: AppWorld's timeouts use SIGALRM); returns when the
             loop asks for the first step
  /fill      jinja2 Template(text).render(instruction, main_user=task.supervisor, app_descriptions)
             (SimplifiedReActCodeAgent.initialize)
  /execute   {"code"} -> {"output", "finish", "end"}: the loop runs the code and asks for the next step,
             or ends the episode ("output" is then the last output, from world.environment_io)
  /stop      the harness stopped: the loop ends at its next step
  /finish    evaluate_task(...) as evaluate_tasks does; returns TestTracker.to_dict(). Runner only.

  APPWORLD_ROOT=... python env_server.py --task-id ID --experiment NAME --port N
"""
import argparse
import json
import os
import queue
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

from jinja2 import Template

os.environ.setdefault("OPENAI_API_KEY", "unused")  # Agent builds a LanguageModel; the harness is the model here

from appworld import AppWorld  # noqa: E402
from appworld.apps.lib.models.db import CachedDBHandler  # noqa: E402
from appworld.evaluator import evaluate_task  # noqa: E402
from appworld_agents.code.common.usage_tracker import Usage  # noqa: E402
from appworld_agents.code.simplified.agent import Agent, ExecutionIO, Status  # noqa: E402

AGENT_CONFIG = {  # experiments/configs/ornith9b_react_dev.jsonnet, without the model (the harness is the agent)
    "model_config": {"name": "harness", "client_name": "openai", "api_type": "chat_completions",
                     "cost_per_token": {"input_cache_hit": 0.0, "input_cache_miss": 0.0,
                                        "input_cache_write": 0.0, "output": 0.0}},
    "appworld_config": {"random_seed": 100, "raise_on_extra_parameters": True},
    "logger_config": {"color": False, "verbose": True},
    "usage_tracker_config": {"max_cost_overall": 1000, "max_cost_per_task": 10, "max_output_tokens_per_task": 100000},
    "max_steps": 50,
}
STOP = object()


class HarnessAgent(Agent):
    def __init__(self):
        super().__init__(**AGENT_CONFIG)
        self.to_harness, self.to_loop = queue.Queue(), queue.Queue()
        self.completed = False

    def next_execution_inputs_usage_and_status(self, last_execution_outputs):
        self.to_harness.put(("step", last_execution_outputs[0].content if last_execution_outputs else None))
        code = self.to_loop.get()
        if code is STOP:
            return [], Usage(), Status(failed=True, message="the harness stopped")
        return [ExecutionIO(content=code)], Usage(), Status(failed=False)

    def log_usage(self):
        super().log_usage()
        self.completed = self.world.task_completed()


class Episode:
    def __init__(self, task_id, experiment):
        self.task_id, self.experiment = task_id, experiment
        self.agent = HarnessAgent()
        self.started = self.over = False

    def _loop(self):
        try:
            self.agent.solve_tasks([self.task_id], experiment_name=self.experiment)
            a = self.agent
            if a.completed:
                end = {"reason": "finished"}
            elif a.step_number >= a.max_steps:
                end = {"reason": "step limit"}
            else:
                end = {"reason": "stopped"}
        except Exception:  # noqa: BLE001
            end = {"reason": "error", "detail": traceback.format_exc(limit=5)}
        io = self.agent.world.environment_io if self.agent.world else []
        self.agent.to_harness.put(("end", {**end, "steps": self.agent.step_number,
                                           "last": io[-1] if io else None}))

    def _next(self, code=None):
        kind, x = self.agent.to_harness.get()
        if kind == "step":
            return {"output": x, "finish": False}
        self.over = True
        last = x.pop("last")
        output = last["output"] if last and code is not None and last["input"] == code else None
        return {"output": output, "finish": True, "end": x}

    def start(self, main):
        assert not self.started
        self.started = True
        main.put(self._loop)
        return self._next()

    def fill(self, text):
        task = self.agent.world.task
        app_descriptions = json.dumps(
            [{"name": k, "description": v} for (k, v) in task.app_descriptions.items()], indent=1)
        return Template(text).render({"instruction": task.instruction, "main_user": task.supervisor,
                                      "app_descriptions": app_descriptions})

    def execute(self, code):
        if self.over:
            raise RuntimeError("episode is over")
        self.agent.to_loop.put(code)
        return self._next(code)

    def stop(self):
        if self.started and not self.over:
            self.agent.to_loop.put(STOP)
            self._next()
        return True

    def finish(self):
        if not CachedDBHandler.is_empty():
            raise RuntimeError("cached DB handler is not empty after close")
        CachedDBHandler.reset()
        tracker = evaluate_task(task_id=self.task_id, experiment_name=self.experiment,
                                suppress_errors=True, save_report=True)
        CachedDBHandler.reset()
        return tracker.to_dict()


def on_main(main, fn):
    """Run fn in the main thread, wait for its result."""
    box = queue.Queue()

    def job():
        try:
            box.put((True, fn()))
        except Exception as e:  # noqa: BLE001
            box.put((False, e))
    main.put(job)
    ok, x = box.get()
    if not ok:
        raise x
    return x


def make_handler(ep, main):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, obj):
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/ready":
                return self.reply(200, True)
            self.reply(404, {"error": self.path})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            try:
                if self.path == "/start":
                    out = ep.start(main)
                elif self.path == "/fill":
                    out = ep.fill(body["text"])
                elif self.path == "/execute":
                    out = ep.execute(body["code"])
                elif self.path == "/stop":
                    out = ep.stop()
                elif self.path == "/finish":
                    ep.stop()
                    out = on_main(main, ep.finish)
                    main.put(None)
                else:
                    return self.reply(404, {"error": self.path})
            except Exception as e:
                return self.reply(500, {"error": repr(e)})
            self.reply(200, out)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    with AppWorld.initializer(update_defaults=True, experiment_name=a.experiment, **AGENT_CONFIG["appworld_config"]):
        ep, main = Episode(a.task_id, a.experiment), queue.Queue()
        server = HTTPServer(("127.0.0.1", a.port), make_handler(ep, main))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        while (job := main.get()) is not None:
            job()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
