"""Счётчики ACE — достояние ACE (и хуков по ошибкам, которые их взяли): метки helpful / harmful извлечения идут
в журнал исходов записи, счётчики — его свёртки; отсев вредных — политика памяти. У остальных уроков журнал свой
(Future IG EvoLib) или его нет."""
from dataclasses import asdict, dataclass

from .record import Lesson

HELPFUL, HARMFUL = "helpful", "harmful"


@dataclass(frozen=True, eq=False)
class Counted(Lesson):
    """Урок со счётчиками helpful / harmful."""

    @property
    def helpful(self):
        return self.outcomes.count(HELPFUL)

    @property
    def harmful(self):
        return self.outcomes.count(HARMFUL)

    def dump(self):
        return dict(asdict(self), helpful=self.helpful, harmful=self.harmful)


def count(memory, helpful, harmful):
    """Метки извлечения — в журналы исходов записей памяти; чужие id пропускаются."""
    for ids, outcome in ((helpful, HELPFUL), (harmful, HARMFUL)):
        for rid in ids:
            r = memory.get(rid)
            if r:
                r.outcomes.append(outcome)


def prune_harmful(memory, at):
    """Отсев: запись уходит, когда вредных меток не меньше at и больше, чем полезных."""
    memory.prune(lambda r: r.harmful >= at and r.harmful > r.helpful)
