"""Решатель MCE апстрима — среда задачи (mce/eval.py batch_evaluate, env/*: aevaluate).

У задачи с интерфейсами (symptom: get_context) — среда апстрима целиком: контекст — get_context(вопрос) из
interfaces/ папки под-итерации (нет интерфейса или он упал — пустой), промпт диагноза одним сообщением user при
T = 0.0 без предела генерации (LLMClient), ответ — _extract_diagnosis. У задач стенда интерфейсов нет (MCE1):
общий решатель видит все файлы context/ и interfaces/."""
from .. import prompts, render
from ..loop import Prompt, Solver
from ..model import Call, messages
from ..tasks import symptom_diagnosis, variant
from ..show import Whole
from . import OwnSolver

DIAGNOSIS = prompts.load("symptom_diagnosis")
PARAMS = {"temperature": 0.0}       # LLMClient апстрима: temperature=0.0, без max_tokens


class Environment(OwnSolver):
    reads = ("interfaces",)

    def __init__(self):
        self.files = Whole(line=render.plain, sep="\n\n")

    def prompt(self, ex, memory, item, k):
        if variant("mce", ex.task) != "symptom":
            return self.files.prompt(ex, memory, item, k)
        get_context = memory.interfaces(ex.task).get("get_context")
        context = ""
        if get_context:
            try:
                context = get_context(item["context"])
                len(context)            # апстрим печатает длину: не строка без len — как упавший интерфейс
            except Exception:
                context = ""
        text = DIAGNOSIS.fill(symptoms=item["context"], context=context)
        return Prompt(solver=Solver(lambda note: Call(messages(text), dict(PARAMS)), symptom_diagnosis))
