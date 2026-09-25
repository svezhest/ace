"""Среда попытки: инструменты решателя, не связанные с памятью (чтение памяти даёт показ).
Цикл открывает среду перед попыткой (open) и закрывает после (close)."""
from .. import prompts, render
from . import sandbox

CALLS = 3                   # вызовов run_python до ответа


class Env:
    """Пустая среда: ответ сразу."""
    rounds = 0
    hint = ""
    tools = ()

    def open(self):
        """Среда одной попытки."""
        return self

    def close(self):
        pass


def run_python(code: str) -> str:
    """Run Python code in a sandbox and return its stdout and stderr."""
    r = sandbox.run(code)
    return render.python_output(r["stdout"], r["stderr"])


class Sandbox(Env):
    """Python в песочнице. per="call" — контейнер на каждый вызов, без состояния (как DC апстрима);
    per="attempt" — контейнер живёт попытку: файлы в /tmp переходят из вызова в вызов, попытки независимы."""
    rounds = CALLS
    hint = "\n" + prompts.text("sandbox_hint")
    tools = (run_python,)

    def __init__(self, per="call"):
        self.per = per

    def open(self):
        return Session() if self.per == "attempt" else self


class Session(Env):
    """Контейнер одной попытки."""
    rounds, hint = Sandbox.rounds, Sandbox.hint

    def __init__(self):
        self.container = sandbox.start()

        def run_python(code: str) -> str:
            """Run Python code in a sandbox and return its stdout and stderr."""
            r = sandbox.run(code, self.container)
            return render.python_output(r["stdout"], r["stderr"])
        self.tools = (run_python,)

    def close(self):
        sandbox.stop(self.container)
