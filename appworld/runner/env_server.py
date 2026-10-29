"""One AppWorld task as a local HTTP service: the black box behind view/src/bridge.py.

Runs in AppWorld's own venv, one process per episode (an AppWorld process holds one world).
Does for one task exactly what AppWorld's runner does (`appworld run` with the simplified ReAct
agent config, then `appworld evaluate`):
  start      AppWorld.initializer(update_defaults=True, experiment_name, random_seed=100,
             raise_on_extra_parameters=True); AppWorld(task_id); set_random_seed(100)
  /fill      jinja2 Template(text).render(instruction, main_user=task.supervisor, app_descriptions)
             (SimplifiedReActCodeAgent.initialize)
  /execute   world.batch_execute([code])[0]          (Agent.solve_task)
  /completed world.task_completed()
  /finish    world.close(), then evaluate_task(...) as evaluate_tasks does; returns
             TestTracker.to_dict(). Called by the runner only, after the episode.

  APPWORLD_ROOT=... python env_server.py --task-id ID --experiment NAME --port N
"""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from jinja2 import Template

from appworld import AppWorld
from appworld.apps.lib.models.db import CachedDBHandler
from appworld.common.random import set_random_seed
from appworld.evaluator import evaluate_task

APPWORLD_CONFIG = {"random_seed": 100, "raise_on_extra_parameters": True}  # upstream appworld_config


class Task:
    def __init__(self, task_id, experiment):
        self.task_id, self.experiment = task_id, experiment
        self.world = AppWorld(task_id=task_id)
        set_random_seed(APPWORLD_CONFIG["random_seed"])  # Agent.initialize
        self.closed = False

    def fill(self, text):
        task = self.world.task
        app_descriptions = json.dumps(
            [{"name": k, "description": v} for (k, v) in task.app_descriptions.items()], indent=1)
        return Template(text).render({"instruction": task.instruction, "main_user": task.supervisor,
                                      "app_descriptions": app_descriptions})

    def execute(self, code):
        if self.closed:
            raise RuntimeError("episode is over")
        return self.world.batch_execute([code])[0]

    def completed(self):
        return False if self.closed else self.world.task_completed()

    def finish(self):
        self.world.close()
        self.closed = True
        if not CachedDBHandler.is_empty():
            raise RuntimeError("cached DB handler is not empty after close")
        CachedDBHandler.reset()
        tracker = evaluate_task(task_id=self.task_id, experiment_name=self.experiment,
                                suppress_errors=True, save_report=True)
        CachedDBHandler.reset()
        return tracker.to_dict()


def make_handler(task, server_ref):
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
            if self.path == "/completed":
                return self.reply(200, task.completed())
            self.reply(404, {"error": self.path})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            try:
                if self.path == "/fill":
                    out = task.fill(body["text"])
                elif self.path == "/execute":
                    out = task.execute(body["code"])
                elif self.path == "/finish":
                    out = task.finish()
                    threading.Thread(target=server_ref[0].shutdown, daemon=True).start()
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
    with AppWorld.initializer(update_defaults=True, experiment_name=a.experiment, **APPWORLD_CONFIG):
        task = Task(a.task_id, a.experiment)
        ref = []
        server = HTTPServer(("127.0.0.1", a.port), make_handler(task, ref))
        ref.append(server)
        server.serve_forever()
        server.server_close()


if __name__ == "__main__":
    main()
