"""Показ ACE: у стенда — все пункты «[id] текст» (Whole по умолчанию); у апстрима — весь playbook текстом
апстрима, строка «[id] helpful=X harmful=Y :: текст», и просьба назвать использованные пункты строкой USED
(вместо bullet_ids)."""
from .. import prompts
from ..memory.ace import layout
from . import Whole

PLAYBOOK = Whole(layout=lambda records, memory: layout(memory), after="\n\n" + prompts.text("solver_used"))
