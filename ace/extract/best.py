"""Best-of-N над любым извлечением: n извлечений одной группы и выбор одного (SCOPE: synthesizer.py, Best-of-N).
Добавки — те же, что у внутреннего извлечения."""
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
