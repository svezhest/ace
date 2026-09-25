"""Исполнение python-кода модели в docker-контейнере без сети и без доступа к хосту.
Контейнер на вызов (run(code)) или на попытку (start -> run(code, container) ... -> stop): внутри попытки
между вызовами живут файлы в /tmp, между попытками — ничего."""
import json
import os
import subprocess

from .. import render

IMAGE = "cestand-sandbox"
TIMEOUT = 10                # секунд на запуск кода внутри контейнера
DOCKER_GRACE = 15           # сверх TIMEOUT на старт и остановку контейнера
HEAD_LINES, TAIL_LINES = 20, 20
MAX_BYTES = 64_000
TIMEOUT_RC = 124            # код возврата timeout(1)

ISOLATION = [
    "--network", "none",
    "--memory", "512m", "--memory-swap", "512m",
    "--cpus", "1",
    "--pids-limit", "64",
    "--read-only", "--tmpfs", "/tmp:size=64m,exec",
    "--security-opt", "no-new-privileges",
    "--cap-drop", "ALL",
]


def python(limit, path=None):
    """Команда в контейнере: код из stdin; с path — сначала в файл path, как запуск файла (в traceback — строки
    кода)."""
    if path:
        return ["sh", "-c", f"cat > {path} && exec timeout {limit} python -I {path}"]
    return ["timeout", str(limit), "python", "-I", "-"]


def trim(text, head=HEAD_LINES, tail=TAIL_LINES):
    text = text[:MAX_BYTES]
    lines = text.splitlines()
    if len(lines) <= head + tail:
        return text
    return "\n".join(lines[:head] + [render.omitted(len(lines) - head - tail)] + lines[-tail:])


def run(code, container=None, limit=TIMEOUT, path=None):
    """-> dict(stdout, stderr, rc, timeout). Код уходит через stdin, обратно только текст.
    container — id контейнера попытки (start); без него — одноразовый контейнер на этот вызов. limit — секунд на код;
    path — исполнить как файл с этим путём внутри контейнера."""
    if container:
        args = ["docker", "exec", "-i", container, *python(limit, path)]
    else:
        args = ["docker", "run", "--rm", "-i", *ISOLATION, IMAGE, *python(limit, path)]
    try:
        p = subprocess.run(args, input=code.encode(), capture_output=True, timeout=limit + DOCKER_GRACE)
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": render.NO_RESPONSE, "rc": -1, "timeout": True}
    out, err = p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
    timed_out = p.returncode == TIMEOUT_RC
    if timed_out:
        err += "\n" + render.time_limit(limit)
    return {"stdout": trim(out), "stderr": trim(err), "rc": p.returncode, "timeout": timed_out}


def start():
    """Контейнер на попытку с той же изоляцией; живёт до stop. -> id."""
    p = subprocess.run(["docker", "run", "-d", "--rm", *ISOLATION, IMAGE, "sleep", "infinity"],
                       capture_output=True, text=True, check=True, timeout=DOCKER_GRACE)
    return p.stdout.strip()


def stop(container):
    subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=DOCKER_GRACE)


def build():
    """Образ песочницы из Dockerfile рядом."""
    d = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(["docker", "build", "-t", IMAGE, d], check=True)


def available():
    """Есть ли docker и собранный образ."""
    try:
        return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


class Kernel:
    """Живой процесс kernel.py в контейнере на попытку (инструмент агента TF-GRPO): один IPython, переменные между
    вызовами. call(аргументы JSON-строкой) -> текст для модели. Ядро, завершившееся по пределу времени, заменяется
    новым при следующем вызове. Код ядра уходит через -c: контейнер только на чтение."""
    ENV = ["-e", "HOME=/tmp", "-e", "MPLCONFIGDIR=/tmp/mpl", "-e", "IPYTHONDIR=/tmp/ipython"]

    def __init__(self):
        self.code = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "kernel.py")).read()
        self.proc = None

    def call(self, arguments):
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(["docker", "run", "--rm", "-i", *ISOLATION, *self.ENV, IMAGE, "python", "-c", self.code],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.proc.stdin.write(json.dumps({"arguments": arguments}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("ядро песочницы завершилось без ответа")
        return json.loads(line)["output"]

    def close(self):
        if self.proc is not None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=DOCKER_GRACE)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
