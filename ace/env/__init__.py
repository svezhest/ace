"""Среда решателя: что он может сделать между вопросом и ответом.

Протокол текстовый, чтобы не зависеть от tool-calling конкретной модели:
блок ```python ... ``` в конце ответа исполняется, `USE SKILL: name` возвращает тело записи.
"""
import re

from . import sandbox

CODE = re.compile(r"```python\n(.*?)```\s*$", re.S)
SKILL = re.compile(r"^USE SKILL:\s*(\S+)", re.M)


class Env:
    """Пустая среда: ответ сразу."""
    rounds = 0
    hint = ""

    def act(self, text, memory):
        return None                          # None = действий нет, ответ окончательный


class Sandbox(Env):
    rounds = 3
    hint = ("\nYou may run Python: end your message with a ```python block and wait for its output "
            "before giving the final answer.")

    def act(self, text, memory):
        m = CODE.search(text)
        if not m:
            return None
        r = sandbox.run(m.group(1))
        return f"[stdout]\n{r['stdout']}\n[stderr]\n{r['stderr']}".strip()


class Skills(Env):
    """Каталог в промпте, тело по вызову. Вызовы пишутся в memory.used."""
    rounds = 3
    hint = "\nTo read a memory entry in full write a line `USE SKILL: <id>` and wait."

    def act(self, text, memory):
        ids = SKILL.findall(text)
        if not ids:
            return None
        memory.used += ids
        return "\n\n".join(f"[{i}] {memory.get(i).text if memory.get(i) else 'no such entry'}" for i in ids)
