"""Память хуков по ошибкам: уроки с триггером; исходы показа — в журнал; хук с тем же trigger и другим текстом —
новая запись со счётчиками с нуля; prune — хук уходит, когда вредных исходов не меньше prune и больше полезных."""
from dataclasses import dataclass

from ..extract import LABELS, TRIGGER
from . import Ids, Lesson, Lessons

PRUNE = 2


@dataclass(frozen=True, eq=False)
class Hook(Lesson):
    """Урок по ошибке: показывается, когда текст ошибки содержит trigger."""
    trigger: str = ""

    def head(self):
        return self.trigger

    def fires(self, text):
        return self.trigger.lower() in text.lower()


class HookBook(Lessons):
    def __init__(self, prune=PRUNE):
        super().__init__("hook", record=Hook, ids=Ids("h"))     # свои id: в показе рядом с записями ученика
        self.prune_at = prune
        self.requires = frozenset({TRIGGER, LABELS}) if prune else frozenset({TRIGGER})

    def learn(self, ex, extractions):
        for x in extractions:
            if LABELS in x.extras:
                self.count(x.extras[LABELS].helpful, x.extras[LABELS].harmful)
            for text, trigger in zip(x.lessons, x.extras[TRIGGER]):
                old = next((r for r in self.items if r.trigger.lower() == trigger.lower()), None)
                if old is None:
                    self.add(text, trigger=trigger)
                elif old.text != text:
                    self.update(old.id, text, trigger=trigger)
        if self.prune_at:
            self.prune(lambda r: r.harmful >= self.prune_at and r.harmful > r.helpful)
