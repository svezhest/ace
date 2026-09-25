"""Показ ACE для общего решателя (ace_used, S1): весь playbook апстрима в системном промпте и просьба назвать
использованные пункты строкой USED. Решатель ACE апстрима — solver/ace.py; у ace_stand показ по умолчанию
(все пункты «[id] текст»)."""
from .. import prompts
from ..memory.ace import layout
from . import Whole

def playbook_layout(records, memory):
    """Весь playbook текстом апстрима, а не выбранные записи."""
    return layout(memory)


PLAYBOOK = Whole(layout=playbook_layout, after="\n\n" + prompts.text("solver_used"), reads=("sections",))
