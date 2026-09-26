"""Инструмент execute_python_code агента TF-GRPO: живой процесс tfgrpo_kernel.py в контейнере песочницы на попытку
(один IPython, переменные между вызовами). call(аргументы JSON-строкой) -> текст для модели.

Предел времени ставит само ядро (timeout вызова, как asyncio.wait_for апстрима) и завершается после него. Хост
ждёт ответ не дольше timeout вызова и запаса на docker: код, держащий GIL (pow(3, 10**9)), ядро прервать не может —
контейнер убивается, модели — тот же текст о пределе времени. Ядро умерло (нехватка памяти убила контейнер) —
модели текст об этом. Следующий вызов начинает новое ядро. Код ядра уходит через -c: контейнер только на чтение."""
import json
import select
import subprocess
from pathlib import Path

from .. import render
from .sandbox import DOCKER_GRACE, IMAGE, ISOLATION, container_name

DEFAULT_TIMEOUT = 30        # timeout execute_python_code_args по умолчанию
CODE = Path(__file__).parent / "tfgrpo_kernel.py"
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
        self.code = CODE.read_text()
        self.proc = None        # процесс docker run с ядром; None — ядра нет
        self.name = None        # имя контейнера

    def start(self):
        self.name = container_name("tfgrpo-kernel")
        command = ["docker", "run", "--rm", "-i", "--name", self.name, *ISOLATION, *ENV, IMAGE,
                   "python", "-c", self.code]
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

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
