"""Инструмент execute_python_code агента TF-GRPO: живой процесс tfgrpo_kernel.py в контейнере песочницы на попытку
(один IPython, переменные между вызовами). call(аргументы JSON-строкой) -> текст для модели.

Предел времени ставит само ядро (timeout вызова, как asyncio.wait_for апстрима) и завершается после него. Хост
ждёт ответ не дольше timeout вызова и запаса на docker: код, держащий GIL (pow(3, 10**9)), ядро прервать не может —
контейнер убивается, модели — тот же текст о пределе времени. Ядро умерло (нехватка памяти убила контейнер) —
модели текст об этом. Следующий вызов начинает новое ядро. Код ядра уходит через -c: контейнер только на чтение."""
import json
import os
import select
import subprocess
import uuid

from .. import render
from .sandbox import DOCKER_GRACE, IMAGE, ISOLATION

DEFAULT_TIMEOUT = 30        # timeout execute_python_code_args по умолчанию
CODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tfgrpo_kernel.py")
ENV = ["-e", "HOME=/tmp", "-e", "MPLCONFIGDIR=/tmp/mpl", "-e", "IPYTHONDIR=/tmp/ipython"]


def timeout_of(arguments):
    """Предел времени вызова из его аргументов; неразобранные аргументы ядро отбивает сразу."""
    try:
        value = json.loads(arguments).get("timeout", DEFAULT_TIMEOUT)
        return value if isinstance(value, int) else DEFAULT_TIMEOUT
    except Exception:
        return DEFAULT_TIMEOUT


class Kernel:
    def __init__(self):
        self.code = open(CODE).read()
        self.proc = self.name = None

    def start(self):
        self.name = f"tfgrpo-kernel-{uuid.uuid4().hex[:12]}"
        self.proc = subprocess.Popen(["docker", "run", "--rm", "-i", "--name", self.name, *ISOLATION, *ENV, IMAGE, "python",
                                      "-c", self.code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def call(self, arguments):
        if self.proc is None or self.proc.poll() is not None:
            self.start()
        timeout = timeout_of(arguments)
        try:
            self.proc.stdin.write(json.dumps({"arguments": arguments}) + "\n")
            self.proc.stdin.flush()
            ready, _, _ = select.select([self.proc.stdout], [], [], timeout + DOCKER_GRACE)
            line = self.proc.stdout.readline() if ready else None
        except OSError:             # труба сломана: ядро уже умерло
            line = ""
        if line:
            return json.loads(line)["output"]
        self.kill()
        return render.kernel_timeout(timeout) if line is None else render.kernel_died()

    def kill(self):
        if self.proc is not None:
            self.proc.kill()
            subprocess.run(["docker", "kill", self.name], capture_output=True, timeout=DOCKER_GRACE)
            self.proc = None

    def close(self):
        if self.proc is None:
            return
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=DOCKER_GRACE)
            self.proc = None
        except (OSError, subprocess.TimeoutExpired):
            self.kill()
