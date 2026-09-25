"""Показ хуков по ошибкам. AFTER — после шага с ошибкой хуки, чей trigger есть в тексте ошибки, сообщением в
конец истории (Patch(append)): исправление. SYSTEM — все хуки в системном промпте с начала попытки:
предотвращение."""
from .. import prompts, render
from . import AfterError, Show, Whole


def fired(records, step):
    """Хуки, показанные после шага step."""
    return [r for r in records if r.fires(step.result)] if step.failed else []


AFTER = AfterError(Show(), lambda memory: memory.records(), trigger=lambda r: r.trigger)
SYSTEM = Whole(layout=lambda records, memory: render.hooks(records), head=prompts.text("hook_system_intro"))
