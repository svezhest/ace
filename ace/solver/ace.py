"""Решатель ACE апстрима — Generator.generate (core/generator.py, промпт ace_generator.j2 дословно): одно сообщение
user с playbook текстом апстрима, рефлексией («(empty)» без неё), вопросом и context задачи (DataProcessor
апстрима); ответ в зачёт — extract_answer. Показ ace_used (общий решатель с playbook) — show/ace.py."""
from .. import parse, prompts
from ..loop import Prompt, Solver
from ..memory.ace import layout
from ..upstream.ace import ace_input, ace_params
from ..model import Call, messages
from . import OwnSolver

TEMPLATE = prompts.load("ace_generator")
NO_REFLECTION = "(empty)"


class Generator(OwnSolver):
    def prompt(self, ex, memory, item, k):
        context, question = ace_input(ex.task.name, item["context"])
        playbook = layout(memory)

        def call(note):
            prompt = TEMPLATE.fill(playbook=playbook, reflection=note or NO_REFLECTION, question=question, context=context)
            return Call(messages(prompt), ace_params())
        return Prompt(shown=[r.id for r in memory.records()], solver=Solver(call, parse.ace_answer))


GENERATOR = Generator()
