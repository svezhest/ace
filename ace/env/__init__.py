"""Среда решателя: tools, доступные между вопросом и ответом. deps каждого tool — Memory."""
from pydantic_ai import RunContext

from . import sandbox
from ..memory import Memory


class Env:
    """Пустая среда: ответ сразу."""
    rounds = 0
    hint = ""
    tools = ()


def run_python(code: str) -> str:
    """Run Python code in a sandbox and return its stdout and stderr."""
    r = sandbox.run(code)
    return f"[stdout]\n{r['stdout']}\n[stderr]\n{r['stderr']}".strip()


def use_skill(ctx: RunContext[Memory], id: str) -> str:
    """Read a memory entry in full by its id from the catalog."""
    ctx.deps.used.append(id)
    rec = ctx.deps.get(id)
    return rec.text if rec else "no such entry"


class Sandbox(Env):
    rounds = 3
    hint = "\nYou may run Python with run_python before giving the final answer."
    tools = (run_python,)


class Skills(Env):
    """Каталог в промпте, тело по вызову use_skill. Вызовы пишутся в memory.used."""
    rounds = 3
    hint = "\nYou may read any catalog entry in full with use_skill(id)."
    tools = (use_skill,)
