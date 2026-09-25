"""Исполнение python-кода модели в docker-контейнере без сети и без доступа к хосту.
Контейнер на вызов (run(code)) или на попытку (start -> run(code, container) ... -> stop): внутри попытки
между вызовами живут файлы в /tmp, между попытками — ничего."""
import subprocess
import time
import uuid

from .. import prompts

IMAGE = "cestand-sandbox"
TEXT = prompts.macros("sandbox")
TIMEOUT = 10                # секунд на запуск кода внутри контейнера
DOCKER_GRACE = 15           # сверх TIMEOUT на старт и остановку контейнера
HEAD_LINES = 20             # длинный вывод: начало и конец, середина вырезается
TAIL_LINES = 20
MAX_BYTES = 64_000
TIMEOUT_RC = 124            # код возврата timeout(1)
KILLED_RC = 137             # timeout(1) добил SIGKILL-ом код, который не вышел по SIGTERM
KILL_AFTER = 1              # секунд от SIGTERM до SIGKILL

MEMORY = "512m"             # память контейнера, без swap
CPUS = "1"
PIDS = "64"                 # процессов в контейнере: fork-бомба не положит хост
TMP_SIZE = "64m"            # /tmp — единственное место для записи

ISOLATION = [
    "--network", "none",
    "--memory", MEMORY, "--memory-swap", MEMORY,
    "--cpus", CPUS,
    "--pids-limit", PIDS,
    "--read-only", "--tmpfs", f"/tmp:size={TMP_SIZE},exec",
    "--security-opt", "no-new-privileges",
    "--cap-drop", "ALL",
]


def python(limit, path=None):
    """Команда в контейнере: код из stdin; с path — сначала в файл path, как запуск файла (в traceback — строки
    кода)."""
    if path:
        return ["sh", "-c", f"cat > {path} && exec timeout -k {KILL_AFTER} {limit} python -I {path}"]
    return ["timeout", "-k", str(KILL_AFTER), str(limit), "python", "-I", "-"]


def trim(text, head=HEAD_LINES, tail=TAIL_LINES):
    text = text[:MAX_BYTES]
    lines = text.splitlines()
    if len(lines) <= head + tail:
        return text
    return "\n".join(lines[:head] + [TEXT.omitted(n=len(lines) - head - tail)] + lines[-tail:])


def run(code, container=None, limit=TIMEOUT, path=None):
    """-> dict(stdout, stderr, rc, timeout). Код уходит через stdin, обратно только текст.
    container — id контейнера попытки (start); без него — одноразовый контейнер на этот вызов. limit — секунд на код;
    path — исполнить как файл с этим путём внутри контейнера."""
    name = f"sandbox-{uuid.uuid4().hex[:12]}"
    if container:
        args = ["docker", "exec", "-i", container, *python(limit, path)]
    else:
        args = ["docker", "run", "--rm", "-i", "--name", name, *ISOLATION, IMAGE, *python(limit, path)]
    t0 = time.time()
    try:
        p = subprocess.run(args, input=code.encode(), capture_output=True, timeout=limit + DOCKER_GRACE)
    except subprocess.TimeoutExpired:       # клиент docker убит, контейнер — ещё нет
        subprocess.run(["docker", "kill", container or name], capture_output=True, timeout=DOCKER_GRACE)
        return {"stdout": "", "stderr": TEXT.no_response(), "rc": -1, "timeout": True}
    out, err = p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
    timed_out = p.returncode == TIMEOUT_RC or p.returncode == KILLED_RC and time.time() - t0 >= limit
    if timed_out:
        err += "\n" + TEXT.time_limit(seconds=limit)
    return {"stdout": trim(out), "stderr": trim(err), "rc": p.returncode, "timeout": timed_out}


def start():
    """Контейнер на попытку с той же изоляцией; живёт до stop. -> id."""
    p = subprocess.run(["docker", "run", "-d", "--rm", *ISOLATION, IMAGE, "sleep", "infinity"],
                       capture_output=True, text=True, check=True, timeout=DOCKER_GRACE)
    return p.stdout.strip()


def stop(container):
    subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=DOCKER_GRACE)


def available():
    """Есть ли docker и собранный образ."""
    try:
        return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False
