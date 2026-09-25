"""Показ ACE: у стенда — все пункты «[id] текст» (Whole по умолчанию); у апстрима — генератор апстрима целиком.

    GENERATOR   решатель ace_exact — Generator.generate апстрима (core/generator.py, промпт ace_generator.j2
                дословно): одно сообщение user с playbook текстом апстрима, рефлексией («(empty)» без неё),
                вопросом и context задачи (DataProcessor апстрима); ответ в зачёт — extract_answer
    PLAYBOOK    ace_exact_used: общий решатель стенда (S1), весь playbook в системном промпте и просьба назвать
                использованные пункты строкой USED"""
from .. import parse, prompts
from ..loop import Prompt, Solver
from ..memory.ace import ace_input, ace_params, layout
from ..model import Call, messages
from . import Show, Whole

TEMPLATE = prompts.load("ace_generator")
NO_REFLECTION = "(empty)"


class Generator(Show):
    def prompt(self, ex, memory, item, k):
        context, question = ace_input(ex.task.name, item["context"])
        playbook = layout(memory)

        def call(note):
            prompt = TEMPLATE.fill(playbook=playbook, reflection=note or NO_REFLECTION, question=question, context=context)
            return Call(messages(prompt), ace_params())
        return Prompt(shown=[r.id for r in memory.records()], solver=Solver(call, parse.ace_answer))


GENERATOR = Generator()
PLAYBOOK = Whole(layout=lambda records, memory: layout(memory), after="\n\n" + prompts.text("solver_used"))
