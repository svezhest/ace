"""Best-of-N над любым извлечением: n извлечений одной группы и выбор одного (SCOPE: synthesizer.py, Best-of-N).
Добавки — те же, что у внутреннего извлечения. one_of_two — селектор наборов уроков (ace_stand_bo2)."""
from .. import prompts, render
from ..model import Call, messages, params
from . import Extractor


class BestOf(Extractor):
    """select(ex, кандидаты) -> номер кандидата; кандидатов меньше двух — выбирать не из чего."""
    def __init__(self, inner, n, select):
        self.inner = inner
        self.n = n
        self.select = select
        self.gives = inner.gives

    def __call__(self, ex, group, memory):
        cands = []
        for _ in range(self.n):
            x = self.inner(ex, group, memory)
            if x:
                cands.append(x)
        if len(cands) < 2:
            return cands[0] if cands else None
        return cands[self.select(ex, cands)]


SELECT = prompts.load("hybrid_select")
SELECTOR = prompts.text("selector_system")


def one_of_two(ex, candidates):
    """Модель выбирает набор уроков: ответ «1» или «2»; без ответа первый."""
    a, b = (render.bullets(x.lessons) for x in candidates[:2])
    out = ex.model.ask(Call(messages(SELECT.fill(a=a, b=b), SELECTOR), params())).output
    return 1 if (out or "1").strip().startswith("2") else 0
