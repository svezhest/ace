"""Показ хуков по ошибкам. AFTER — после шага с ошибкой хуки, чей trigger есть в тексте ошибки, сообщением в
конец истории (Patch(append)): исправление. SYSTEM — все хуки в системном промпте с начала попытки:
предотвращение."""
from .. import prompts, render
from . import AfterError, Show, Whole


def fired(records, step):
    """Хуки, показанные после шага step: только после ошибки исполнения (ошибка вызова инструмента — не урок кода)."""
    return [r for r in records if r.fires(step.result)] if step.exec_error else []


def hooks_layout(records, memory):
    return render.hooks(records)


AFTER = AfterError(Show())
SYSTEM = Whole(layout=hooks_layout, head=prompts.text("hook_system_intro"))
