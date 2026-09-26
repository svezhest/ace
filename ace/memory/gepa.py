"""Память GEPA: кандидат (gepa-ai/gepa: core/state.py program_candidates). У DefaultAdapter апстрима компонент один
— системный промпт (evaluate берёт первый), поэтому выбор компонента round_robin всегда даёт его. Пул кандидатов,
Парето-фронт и выбор родителя — мета-уровень (wrap/gepa.py)."""
from ..extract import LESSONS
from . import Document, Record


class Instruction(Document):
    """Текст системного промпта; до первой рефлексии его нет — решатель и рефлексия видят seed задачи
    (upstream/gepa.py: current). Рефлексия дала текст — он весь и есть новый кандидат (new_candidate[name] = text),
    даже если совпал с прошлым: версия в ключе."""
    requires = frozenset({LESSONS})

    def __init__(self):
        super().__init__(None, "system_prompt")
        self.version = 0

    def key(self):
        return self.version, self.text

    def records(self):
        return [Record(self.kind, self.text)] if self.text is not None else []

    def chars(self):
        return len(self.text or "")

    def dump(self):
        return [dict(kind=self.kind, id=self.kind, text=self.text)] if self.text is not None else []

    def learn(self, ex, extractions):
        for x in extractions:
            self.rewrite(x.lessons[0])
            self.version += 1
