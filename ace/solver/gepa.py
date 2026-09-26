"""Решатель GEPA апстрима — DefaultAdapter.evaluate (adapters/default_adapter/default_adapter.py): системный промпт —
текст кандидата, user — вход задачи как есть, параметров запроса нет (LM(model) без kwargs: у сервера по умолчанию);
ответ — текст без пробелов по краям (LM.batch_complete). В зачёт у aime — весь ответ (ContainsAnswerEvaluator ищет
в нём «### N»), у задач стенда — строка FINAL ANSWER (S2)."""
from ..loop import Prompt, Solver
from ..model import Call, Reader
from ..tasks import final_answer, variant
from ..upstream.gepa import current
from . import OwnSolver


def stripped(text):
    """LMOutput(content or "").strip()."""
    return (text or "").strip()


def whole(text):
    return text


class Adapter(OwnSolver):
    reads = ("text",)

    def prompt(self, ex, memory, item, k):
        system = current(memory, ex.task)
        answer = whole if variant("gepa", ex.task) == "aime" else final_answer

        def call(note):
            # системный — всегда, и пустой: адаптер не пропускает его
            chat = [{"role": "system", "content": system}, {"role": "user", "content": item["question"]}]
            return Call(chat, {}, Reader(text=stripped))
        return Prompt(shown=[r.id for r in memory.records()], solver=Solver(call, answer))


ADAPTER = Adapter()
