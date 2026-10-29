"""Один эпизод AppWorld: задача — отдельный процесс env_server.py в venv AppWorld ($APPWORLD_PY, данные —
$APPWORLD_DATA), harness.run из src/ ходит к нему через bridge.Episode; после эпизода — проверка бенчмарка."""
import json
import os
import socket
import subprocess
import time
import traceback
import urllib.request
from pathlib import Path

import bridge
import harness
from llm import Client, EpisodeEnd

HERE = Path(__file__).resolve().parent


def post(url, payload=None, timeout=900):
    data = None if payload is None else json.dumps(payload).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
        return json.loads(r.read())


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_task(task, experiment, root, log):
    """AppWorld на одну задачу; root — свой APPWORLD_ROOT прогона (data -> $APPWORLD_DATA, outputs пишутся сюда)."""
    url = f"http://127.0.0.1:{free_port()}"
    env = dict(os.environ, APPWORLD_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    proc = subprocess.Popen([os.environ["APPWORLD_PY"], str(HERE / "env_server.py"), "--task-id", task,
                             "--experiment", experiment, "--port", url.rsplit(":", 1)[1]],
                            cwd=str(root), env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 300
    while True:
        try:
            post(url + "/ready", timeout=5)
            return proc, url
        except Exception:
            if proc.poll() is not None or time.time() > deadline:
                proc.kill()
                raise RuntimeError(f"benchmark did not start, see {log.name}")
            time.sleep(0.5)


def hint(evaluation, level):
    """1: сколько проверок бенчмарка прошло; 2: + требования проваленных."""
    if level <= 0 or not evaluation:
        return None
    n, fails = evaluation["num_tests"], evaluation["failures"]
    text = f"{n - len(fails)} of {n} checks passed"
    if level >= 2 and fails:
        text += "; failed: " + " | ".join(" ".join(f["requirement"].split()) for f in fails)
    return text


def play(job):
    root = Path(job["out"]) / "appworld"
    root.mkdir(exist_ok=True)
    if not (root / "data").exists():
        try:
            (root / "data").symlink_to(os.environ["APPWORLD_DATA"])
        except FileExistsError:
            pass
    t0, reason, detail, messages = time.time(), None, "", None
    with open(root / f"env_{job['run']}.log", "w") as log:
        proc, url = start_task(job["task"], f"run_{job['run']}", root, log)
        try:
            llm = Client(job["url"], job["model"], bridge.STEP_LIMIT, job["wall_limit"])
            try:
                messages = harness.run(bridge.Episode(url), llm)
            except EpisodeEnd as e:
                reason, detail = e.reason, e.detail
            except Exception:
                reason, detail = "harness error", traceback.format_exc(limit=5)
            completed = post(url + "/completed")
            evaluation = post(url + "/finish", {})
        finally:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
    if not isinstance(messages, list):
        messages = llm.conversation or []
    if evaluation["success"]:
        reason = "success"
    elif completed:
        reason = "wrong result"
    elif reason is None:
        reason = "step limit" if len(llm.calls) >= bridge.STEP_LIMIT else "harness stopped early"
    return {"run": job["run"], "ok": reason == "success", "reason": reason, "hint": hint(evaluation, job["hint_level"]),
            "messages": messages,
            "meta": {"detail": detail, "completed": completed, "evaluation": evaluation,
                     "sec": round(time.time() - t0, 1), "model_calls": len(llm.calls),
                     "max_prompt_tokens": max((c["prompt_tokens"] or 0 for c in llm.calls), default=0)}}
