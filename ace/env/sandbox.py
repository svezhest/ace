"""Исполнение python-кода модели в одноразовом docker-контейнере без сети и без доступа к хосту."""
import subprocess

from .. import render

IMAGE = "cestand-sandbox"
TIMEOUT = 10                # секунд на запуск кода внутри контейнера
DOCKER_GRACE = 15           # сверх TIMEOUT на старт и остановку контейнера
HEAD_LINES, TAIL_LINES = 20, 20
MAX_BYTES = 64_000
TIMEOUT_RC = 124            # код возврата timeout(1)

DOCKER_ARGS = [
    "docker", "run", "--rm", "-i",
    "--network", "none",
    "--memory", "512m", "--memory-swap", "512m",
    "--cpus", "1",
    "--pids-limit", "64",
    "--read-only", "--tmpfs", "/tmp:size=64m,exec",
    "--security-opt", "no-new-privileges",
    "--cap-drop", "ALL",
    IMAGE, "timeout", str(TIMEOUT), "python", "-I", "-",
]


def trim(text, head=HEAD_LINES, tail=TAIL_LINES):
    text = text[:MAX_BYTES]
    lines = text.splitlines()
    if len(lines) <= head + tail:
        return text
    return "\n".join(lines[:head] + [render.omitted(len(lines) - head - tail)] + lines[-tail:])


def run(code):
    """-> dict(stdout, stderr, rc, timeout). Код уходит через stdin, обратно только текст."""
    try:
        p = subprocess.run(DOCKER_ARGS, input=code.encode(), capture_output=True, timeout=TIMEOUT + DOCKER_GRACE)
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": render.NO_RESPONSE, "rc": -1, "timeout": True}
    out, err = p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
    timed_out = p.returncode == TIMEOUT_RC
    if timed_out:
        err += "\n" + render.time_limit(TIMEOUT)
    return {"stdout": trim(out), "stderr": trim(err), "rc": p.returncode, "timeout": timed_out}


def build():
    """Образ песочницы из Dockerfile рядом."""
    import os
    d = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(["docker", "build", "-t", IMAGE, d], check=True)


def available():
    """Есть ли docker и собранный образ."""
    try:
        return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False
