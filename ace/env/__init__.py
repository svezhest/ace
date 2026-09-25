"""Среда попытки: инструменты решателя, не связанные с памятью (чтение памяти даёт показ).
Цикл открывает среду перед попыткой (open) и закрывает после (close)."""
from .. import prompts, render
from . import sandbox

CALLS = 3                   # вызовов run_python до ответа
TEXT = prompts.macros("sandbox")


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


class Sandbox(Env):
    """Python в песочнице. per="call" — контейнер на каждый вызов, без состояния (как DC апстрима);
    per="attempt" — контейнер живёт попытку: файлы в /tmp переходят из вызова в вызов, попытки независимы."""
    rounds = CALLS
    hint = "\n" + prompts.text("sandbox_hint")

    def __init__(self, per="call"):
        self.per = per
        self.container = None           # контейнер попытки (Session); None — одноразовый на каждый вызов

    @property
    def tools(self):
        return (self.run_python,)

    def open(self):
        return Session() if self.per == "attempt" else self

    @prompts.tool(TEXT.run_python())
    def run_python(self, code: str) -> str:
        """Код в контейнере; модели — stdout и stderr."""
        r = sandbox.run(code, self.container)
        return render.python_output(r["stdout"], r["stderr"])


class Session(Sandbox):
    """Контейнер одной попытки: от open до close."""
    def __init__(self):
        super().__init__("attempt")
        self.container = sandbox.start()

    def close(self):
        sandbox.stop(self.container)
