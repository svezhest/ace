"""Показ ACE для общего решателя (ace_used, S1): весь playbook апстрима в системном промпте и просьба назвать
использованные пункты строкой USED. Решатель ACE апстрима — solver/ace.py; у ace_stand показ по умолчанию
(все пункты «[id] текст»)."""
from .. import prompts
from ..memory.ace import layout
from . import Whole

PLAYBOOK = Whole(layout=lambda records, memory: layout(memory), after="\n\n" + prompts.text("solver_used"), reads=("sections",))
