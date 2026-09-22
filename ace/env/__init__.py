"""Среда решателя: tools, доступные между вопросом и ответом. deps выдаёт env.deps(memory)."""
from . import sandbox
from .. import fs


class Env:
    """Пустая среда: ответ сразу."""
    rounds = 0
    hint = ""
    tools = ()

    def deps(self, memory):
        return memory


def run_python(code: str) -> str:
    """Run Python code in a sandbox and return its stdout and stderr."""
    r = sandbox.run(code)
    return f"[stdout]\n{r['stdout']}\n[stderr]\n{r['stderr']}".strip()


class Sandbox(Env):
    rounds = 3
    hint = "\nYou may run Python with run_python before giving the final answer."
    tools = (run_python,)


class Skills(Env):
    """Каталог в промпте, тело по read из каталога skills/ только на чтение. Чтения пишутся в memory.used."""
    rounds = 3
    hint = "\nYou may read any catalog entry in full with read(path)."
    tools = fs.READ_TOOLS

    def __init__(self, kinds=()):
        self.kinds = kinds

    def deps(self, memory):
        return fs.FS({"skills": fs.Mount(memory, self.kinds, "ro", track=True)})
