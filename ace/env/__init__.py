"""Среда задачи: инструменты решателя, не связанные с памятью. Чтение памяти даёт инжект."""
from .. import prompts, render
from . import sandbox


class Env:
    """Пустая среда: ответ сразу."""
    rounds = 0
    hint = ""
    tools = ()


def run_python(code: str) -> str:
    """Run Python code in a sandbox and return its stdout and stderr."""
    r = sandbox.run(code)
    return render.python_output(r["stdout"], r["stderr"])


class Sandbox(Env):
    rounds = 3
    hint = "\n" + prompts.text("sandbox_hint")
    tools = (run_python,)
