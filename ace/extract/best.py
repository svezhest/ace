"""Best-of-N над любым извлечением: n извлечений одной группы и выбор одного (SCOPE: synthesizer.py, Best-of-N).
Добавки — те же, что у внутреннего извлечения. one_of_two — селектор наборов уроков (ace_stand_bo2)."""
from .. import prompts, render
from ..model import Call, messages, params
from . import Extractor


class BestOf(Extractor):
    """select(ex, group, кандидаты) -> номер кандидата или None (тогда первый); кандидатов меньше двух —
    выбирать не из чего."""
    def __init__(self, inner, n, select):
        self.inner, self.n, self.select = inner, n, select
        self.gives = inner.gives

    def __call__(self, ex, group, memory):
        cands = [x for x in (self.inner(ex, group, memory) for _ in range(self.n)) if x]
        if len(cands) < 2:
            return cands[0] if cands else None
        i = self.select(ex, group, cands)
        return cands[i] if i is not None and 0 <= i < len(cands) else cands[0]


SELECT = prompts.load("hybrid_select")
SELECTOR = prompts.text("selector_system")


def one_of_two(ex, group, candidates):
    """Модель выбирает набор уроков: ответ «1» или «2»; без ответа первый."""
    a, b = (render.bullets(x.lessons) for x in candidates[:2])
    out = ex.model.ask(Call(messages(SELECT.fill(a=a, b=b), SELECTOR), params())).output
    return 1 if (out or "1").strip().startswith("2") else 0
